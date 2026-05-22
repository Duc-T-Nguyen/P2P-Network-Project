import hashlib
import os
import random
import socket
import struct
import sys
import threading
import time
import requests
import traceback
from urllib.parse import urlencode
from Bencode import bdecode


# Peer  –  handles one P2P connection

class Peer:
    def __init__(self, ip, port, info, peer_id, client, manager):
        self.ip = ip
        self.port = port
        self.info = info
        self.peer_id = peer_id
        self.client = client
        self.manager = manager
        self.thread = None
        self.socket = None
        self.choking = True
        self.peer_choking = True
        self.interest = False
        self.peer_interest = False
        self.peer_bit_field = None
        self.running = False

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)
            self.socket.connect((self.ip, self.port))
            if not self.handshake():
                return False
            self.running = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            return True
        except Exception:
            print(f'Error connecting to {self.ip}:{self.port}')
            return False

    def handshake(self):
        proto = b'BitTorrent protocol'
        msg = struct.pack('B', len(proto)) + proto + b'\x00' * 8 + self.info + self.peer_id
        self.socket.send(msg)
        response = self.socket.recv(68)
        if len(response) < 68:
            return False
        if response[28:48] != self.info:
            return False
        print(f'Handshake OK  {self.ip}:{self.port}')
        return True

    def run(self):
        try:
            self.send_bit_field()
            self.send_interested()
            time.sleep(0.1)
            while self.running:
                msg_type, payload = self.receive_message()
                if msg_type is None:
                    break
                self.handle_message(msg_type, payload)
        except Exception as e:
            print(f'Peer error {self.ip}:{self.port}: {e}')
        finally:
            self.close()

    def receive_message(self):
        try:
            raw = self.socket.recv(4)
            if len(raw) < 4:
                return None, None
            length = struct.unpack('>I', raw)[0]
            if length == 0:
                return 'keep_alive', None
            type_byte = self.socket.recv(1)
            if not type_byte:
                return None, None
            msg_type = type_byte[0]
            payload = b''
            if length > 1:
                payload = self.socket.recv(length - 1)
            return msg_type, payload
        except socket.timeout:
            return 'keep_alive', None
        except Exception:
            return None, None

    def handle_message(self, msg_type, payload):
        if msg_type == 'keep_alive':
            return
        elif msg_type == 0:   # choke
            self.peer_choking = True
        elif msg_type == 1:   # unchoke
            self.peer_choking = False
            self.ask_pieces()
        elif msg_type == 2:   # interested
            self.peer_interest = True
            self.unchoke()
        elif msg_type == 3:   # not interested
            self.peer_interest = False
        elif msg_type == 4:   # have
            idx = struct.unpack('>I', payload)[0]
            if self.peer_bit_field is None:
                self.peer_bit_field = [False] * self.manager.num_pieces
            if idx < len(self.peer_bit_field):
                self.peer_bit_field[idx] = True
        elif msg_type == 5:   # bitfield
            self.peer_bit_field = self._parse_bitfield(payload)
            if not self.peer_choking:
                self.ask_pieces()
        elif msg_type == 6:   # request
            self.handle_request(payload)
        elif msg_type == 7:   # piece
            self.handle_piece(payload)

    def _parse_bitfield(self, raw):
        bits = []
        for byte in raw:
            for i in range(8):
                bits.append((byte >> (7 - i)) & 1 == 1)
        return bits[:self.manager.num_pieces]

    def send_message(self, msg_type, payload=b''):
        try:
            length = len(payload) + 1
            msg = struct.pack('>I', length) + struct.pack('B', msg_type) + payload
            self.socket.send(msg)
        except Exception as e:
            print(f'Send error {self.ip}:{self.port}: {e}')

    def send_bit_field(self):
        self.send_message(5, self.manager.get_bit_field())

    def send_interested(self):
        self.interest = True
        self.send_message(2)

    def unchoke(self):
        self.choking = False
        self.send_message(1)

    def have(self, index):
        self.send_message(4, struct.pack('>I', index))

    def ask_pieces(self):
        if self.peer_choking or self.peer_bit_field is None:
            return
        requested = 0
        for index in range(self.manager.num_pieces):
            if (not self.manager.have(index)
                    and self.peer_bit_field[index]
                    and not self.manager.is_piece_requested(index)):
                self.manager.mark_piece(index)
                self.request(index)
                requested += 1
                if requested >= 3:
                    break

    def request(self, index):
        p_size = self.manager.get_size(index)
        b_size = 16384
        for off in range(0, p_size, b_size):
            length = min(b_size, p_size - off)
            self.send_message(6, struct.pack('>III', index, off, length))

    def handle_request(self, payload):
        if self.choking:
            return
        index, off, length = struct.unpack('>III', payload)
        if not self.manager.have(index):
            return
        data = self.manager.get_data(index)
        block = data[off:off + length]
        self.send_message(7, struct.pack('>II', index, off) + block)

    def handle_piece(self, payload):
        index, off = struct.unpack('>II', payload[:8])
        block = payload[8:]
        if self.manager.add_block(index, off, block):
            self.client.broadcast_have(index)
            self.ask_pieces()

    def close(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# MultiFilePieceManager  –  maps the flat piece stream onto multiple files
# ---------------------------------------------------------------------------

class MultiFilePieceManager:

    def __init__(self, torrent, output_dir='.', progress_callback=None):
        """
        torrent          : Torrent instance
        output_dir       : directory where files are written
        progress_callback: optional callable(info: dict) called after each
                           verified piece.  info keys:
                             pieces_done, num_pieces, percent,
                             speed_bps, files (list of file dicts with
                             path/length/downloaded/percent)
        """
        self.torrent = torrent
        self.output_dir = output_dir
        self.progress_callback = progress_callback
        self.num_pieces = torrent.num_pieces()
        self.piece_length = torrent.piece_length()

        self.pieces = [None] * self.num_pieces
        self.piece_status = [False] * self.num_pieces
        self.piece_requested = [False] * self.num_pieces
        self.blocks_received = [set() for _ in range(self.num_pieces)]
        self.lock = threading.Lock()

        # Speed tracking
        self._bytes_since_last = 0
        self._last_speed_time = time.time()
        self._speed_bps = 0.0

        # Build file info table and open handles
        self._file_info = torrent.files()   # list of {path, length, offset}
        self._file_handles = {}
        self._prep_files()

    # File preparation

    def _prep_files(self):
        for fi in self._file_info:
            full_path = os.path.join(self.output_dir, fi['path'])
            os.makedirs(os.path.dirname(full_path) if os.path.dirname(full_path) else '.', exist_ok=True)
            if not os.path.exists(full_path):
                with open(full_path, 'wb') as fh:
                    if fi['length'] > 0:
                        fh.seek(fi['length'] - 1)
                        fh.write(b'\x00')
            self._file_handles[fi['path']] = open(full_path, 'r+b')

    def have(self, index):
        with self.lock:
            return self.piece_status[index]

    def is_piece_requested(self, index):
        with self.lock:
            return self.piece_requested[index]

    def mark_piece(self, index):
        with self.lock:
            self.piece_requested[index] = True

    def get_size(self, index):
        return self.torrent.get_piece_size(index)

    def get_bit_field(self):
        with self.lock:
            bf = bytearray((self.num_pieces + 7) // 8)
            for i, has in enumerate(self.piece_status):
                if has:
                    bf[i // 8] |= 1 << (7 - i % 8)
            return bytes(bf)

    def add_block(self, index, off, block):
        with self.lock:
            if self.pieces[index] is None:
                self.pieces[index] = bytearray(self.get_size(index))
            self.pieces[index][off:off + len(block)] = block
            self.blocks_received[index].add(off)
            if self._is_complete(index):
                return self._verify_save(index)
            return False

    def get_data(self, index):
        """Read piece data back from disk (used when seeding)."""
        with self.lock:
            if not self.piece_status[index]:
                return None
        piece_offset = index * self.piece_length
        piece_size = self.get_size(index)
        data = bytearray(piece_size)
        remaining = piece_size
        local_off = 0
        abs_off = piece_offset
        for fi in self._file_info:
            if abs_off >= fi['offset'] + fi['length']:
                continue
            if abs_off + remaining <= fi['offset']:
                break
            file_start = max(abs_off - fi['offset'], 0)
            write_start = max(fi['offset'] - abs_off, 0)
            can_read = min(remaining - write_start,
                           fi['length'] - file_start)
            if can_read <= 0:
                continue
            fh = self._file_handles[fi['path']]
            fh.seek(file_start)
            chunk = fh.read(can_read)
            data[write_start:write_start + len(chunk)] = chunk
            local_off += len(chunk)
        return bytes(data)

    def complete(self):
        with self.lock:
            return all(self.piece_status)

    def progress(self):
        with self.lock:
            done = sum(self.piece_status)
            return done / self.num_pieces * 100

    def get_progress_info(self):
        """Returns a rich dict for the UI."""
        with self.lock:
            done = sum(self.piece_status)
            pct = done / self.num_pieces * 100

            # per-file progress
            file_progress = []
            for fi in self._file_info:
                fl = fi['length']
                if fl == 0:
                    file_progress.append({**fi, 'downloaded': 0, 'percent': 100})
                    continue
                # bytes of this file covered by completed pieces
                downloaded = self._file_downloaded_bytes(fi)
                file_progress.append({
                    'path': fi['path'],
                    'length': fl,
                    'downloaded': downloaded,
                    'percent': round(downloaded / fl * 100, 1),
                })

            return {
                'pieces_done': done,
                'num_pieces': self.num_pieces,
                'percent': round(pct, 2),
                'speed_bps': round(self._speed_bps, 0),
                'files': file_progress,
            }

    def close(self):
        for fh in self._file_handles.values():
            try:
                fh.close()
            except Exception:
                pass

    # Internal helpers

    def _is_complete(self, index):
        if self.pieces[index] is None:
            return False
        block_size = 16384
        total = (self.get_size(index) + block_size - 1) // block_size
        return len(self.blocks_received[index]) == total

    def _verify_save(self, index):
        piece_data = bytes(self.pieces[index])
        if hashlib.sha1(piece_data).digest() != self.torrent.get_piece_hash(index):
            # Hash mismatch – discard and allow re-download
            self.pieces[index] = None
            self.piece_requested[index] = False
            self.blocks_received[index].clear()
            return False

        # Write piece bytes into the correct file(s)
        abs_start = index * self.piece_length
        remaining = len(piece_data)
        local_off = 0

        for fi in self._file_info:
            file_end = fi['offset'] + fi['length']
            if abs_start + local_off >= file_end:
                continue
            if fi['offset'] >= abs_start + len(piece_data):
                break
            # How many bytes of this piece go into this file
            start_in_file = max(abs_start + local_off - fi['offset'], 0)
            piece_byte_start = max(fi['offset'] - abs_start, 0)
            can_write = min(len(piece_data) - piece_byte_start,
                            fi['length'] - start_in_file)
            if can_write <= 0:
                continue
            fh = self._file_handles[fi['path']]
            fh.seek(start_in_file)
            fh.write(piece_data[piece_byte_start:piece_byte_start + can_write])
            fh.flush()
            local_off += can_write

        self.piece_status[index] = True
        self.piece_requested[index] = False
        self.blocks_received[index].clear()
        self.pieces[index] = None

        # Speed tracking
        now = time.time()
        self._bytes_since_last += len(piece_data)
        elapsed = now - self._last_speed_time
        if elapsed >= 1.0:
            self._speed_bps = self._bytes_since_last / elapsed
            self._bytes_since_last = 0
            self._last_speed_time = now

        # Fire progress callback
        if self.progress_callback:
            try:
                self.progress_callback(self.get_progress_info())
            except Exception:
                pass

        return True

    def _file_downloaded_bytes(self, fi):
        """Estimate bytes of `fi` covered by completed pieces (approx, no lock needed)."""
        total = 0
        piece_len = self.piece_length
        for i, done in enumerate(self.piece_status):
            if not done:
                continue
            p_start = i * piece_len
            p_end = p_start + self.get_size(i)
            f_start = fi['offset']
            f_end = fi['offset'] + fi['length']
            overlap_start = max(p_start, f_start)
            overlap_end = min(p_end, f_end)
            if overlap_end > overlap_start:
                total += overlap_end - overlap_start
        return total


# Keep old name as alias for backwards compatibility
PieceManager = MultiFilePieceManager


# BitTorrentClient

class BitTorrentClient:
    def __init__(self, torrent_path, output_dir=None, progress_callback=None):
        self.torrent_path = torrent_path
        self.output_dir = output_dir or '.'
        self.progress_callback = progress_callback
        self.peer_id = self._gen_peer_id()
        self.torrent = None
        self.piece_manager = None
        self.peers = []
        self.peer_lock = threading.Lock()
        self.port = 6881
        self.server_socket = None
        self.running = False

    def _gen_peer_id(self):
        return b'-PC0001-' + ''.join([str(random.randint(0, 9)) for _ in range(12)]).encode()

    def start(self):
        from Torrent import Torrent
        print(f"Loading torrent: {self.torrent_path}")
        self.torrent = Torrent(self.torrent_path)

        print(f"Name       : {self.torrent.file_name()}")
        print(f"Total size : {self.torrent.file_length()} bytes")
        print(f"Pieces     : {self.torrent.num_pieces()}")
        print(f"Multi-file : {self.torrent.is_multi_file()}")
        if self.torrent.is_multi_file():
            for f in self.torrent.files():
                print(f"  {f['path']}  ({f['length']} bytes)")

        self.piece_manager = MultiFilePieceManager(
            self.torrent,
            output_dir=self.output_dir,
            progress_callback=self.progress_callback,
        )

        self._start_server()
        peers = self._contact_tracker('started')
        if not peers:
            print("No peers from tracker.")
            return
        self._connect_to_peers(peers)
        self._monitor()

    def _start_server(self):
        def _serve():
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                port = 6881
                for attempt in range(10):
                    try:
                        self.server_socket.bind(('0.0.0.0', port))
                        break
                    except OSError:
                        port += 1
                self.port = port
                self.server_socket.listen(5)
                print(f"Listening on port {port}")
                while self.running:
                    try:
                        self.server_socket.settimeout(1)
                        client_sock, addr = self.server_socket.accept()
                        threading.Thread(
                            target=self._handle_incoming,
                            args=(client_sock, addr),
                            daemon=True,
                        ).start()
                    except socket.timeout:
                        continue
                    except Exception:
                        break
            except Exception as e:
                print(f"Server error: {e}")

        self.running = True
        threading.Thread(target=_serve, daemon=True).start()
        time.sleep(0.5)

    def _handle_incoming(self, client_socket, address):
        try:
            response = client_socket.recv(68)
            if len(response) < 68 or response[28:48] != self.torrent.info:
                client_socket.close()
                return
            proto = b'BitTorrent protocol'
            msg = struct.pack('B', len(proto)) + proto + b'\x00' * 8 + self.torrent.info + self.peer_id
            client_socket.send(msg)
            ip, port = address
            peer = Peer(ip, port, self.torrent.info, self.peer_id, self, self.piece_manager)
            peer.socket = client_socket
            peer.running = True
            peer.thread = threading.Thread(target=peer.run, daemon=True)
            peer.thread.start()
            with self.peer_lock:
                self.peers.append(peer)
        except Exception as e:
            print(f"Incoming peer error {address}: {e}")
            try:
                client_socket.close()
            except Exception:
                pass

    def _contact_tracker(self, event):
        info_hash_encoded = ''.join(f'%{b:02x}' for b in self.torrent.info)
        try:
            params = {
                'peer_id': self.peer_id.decode('latin-1'),
                'port': self.port,
                'uploaded': 0,
                'downloaded': 0,
                'left': self.torrent.file_length(),
                'event': event,
                'compact': 0,
            }
            announce = self.torrent.announce()
            if isinstance(announce, bytes):
                announce = announce.decode('utf-8')
            url = announce + '?info_hash=' + info_hash_encoded + '&' + urlencode(params)
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                decoded = bdecode(resp.content)
                return decoded.get('peers', [])
        except Exception as e:
            print(f"Tracker error: {e}")
        return []

    def _connect_to_peers(self, peer_list):
        for pi in peer_list[:5]:
            try:
                ip = pi.get('ip', '')
                if isinstance(ip, bytes):
                    ip = ip.decode('utf-8')
                port = pi.get('port', 0)
                peer_id = pi.get('peerid', b'')
                if peer_id == self.peer_id:
                    continue
                if ip and port:
                    peer = Peer(ip, port, self.torrent.info, self.peer_id, self, self.piece_manager)
                    if peer.connect():
                        with self.peer_lock:
                            self.peers.append(peer)
            except Exception as e:
                print(f"Peer connect error: {e}")

    def broadcast_have(self, index):
        with self.peer_lock:
            for peer in self.peers:
                peer.have(index)

    def _monitor(self):
        if self.piece_manager.complete():
            print("Seeding. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                self.cleanup()
            return

        while not self.piece_manager.complete():
            time.sleep(2)
            info = self.piece_manager.get_progress_info()
            with self.peer_lock:
                peers = len(self.peers)
            print(f"Progress: {info['percent']:.1f}%  speed: {info['speed_bps']/1024:.1f} KB/s  peers: {peers}")

        print("Download complete!")
        self._contact_tracker('completed')
        self.cleanup()

    def cleanup(self):
        self.running = False
        with self.peer_lock:
            for peer in self.peers:
                peer.close()
        if self.server_socket:
            self.server_socket.close()
        if self.piece_manager:
            self.piece_manager.close()


# CLI entry point

def main():
    if len(sys.argv) < 2:
        print("Usage: python Peer.py <torrent_file> [output_dir]")
        sys.exit(1)

    torrent_file = sys.argv[1]
    if not os.path.exists(torrent_file):
        print(f"File not found: {torrent_file}")
        sys.exit(1)

    output_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
    client = BitTorrentClient(torrent_file, output_dir=output_dir)
    client.start()


if __name__ == '__main__':
    main()