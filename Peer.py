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


class Peer:
    def __init__(self, ip, port, info, peer_id, client, manager ):
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
        except Exception as error:
            print(f'Error in connecting to ip={self.ip}:port={self.port}')
            return False
    def handshake(self):
        i = b'BitTorrent protocol'
        i_length = len(i)
        space = b'\x00'*8
        msg = struct.pack('B', i_length)+ i + space + self.info + self.peer_id
        self.socket.send(msg)
        response = self.socket.recv(68)
        if len(response) < 68:
            return False
        receive_length = response[0]
        receive_info = response[28:48]
        if receive_info != self.info:
            return False
        print(f'Handshake is successful with ip={self.ip}:port={self.port}')
        return True
    def run(self):
        try: 
            self.send_bit_field()
            self.send_interested()
            time.sleep(0.1)
            while self.running: 
                type, payload = self.receive_message()
                if type is None: 
                    break
                else:
                    self.handle_message(type, payload)
        except Exception as error:
            print(f'Error in peer conenction ip={self.ip}:port={self.port}  ')
            print(f'Error: {error}')
            traceback.print_exc()
        finally: 
            self.close()
    def recv_exactly(self, num_bytes):
        data = b''
        while len(data) < num_bytes:
            chunk = self.socket.recv(num_bytes-len(data))
            if not chunk:
                return None
            data += chunk
        return data
    def receive_message(self):
        try: 
            byte_length = self.recv_exactly(4)
            if byte_length is None or len(byte_length) < 4:
                return None, None
            length = struct.unpack('>I', byte_length)[0]
            if length == 0:
                return 'keep_alive', None
            message_type_byte = self.recv_exactly(1)
            if message_type_byte is None or len(message_type_byte) < 1:
                return None, None
            type = message_type_byte[0]
            payload = b''
            if length>1:
                payload = self.recv_exactly(length - 1) or b''
            return type, payload
        except socket.timeout:
            return 'keep_alive', None
        except Exception as error:
            return None, None
    def handle_message(self, type, payload):
        message_types = {0: 'choke', 1: 'unchoke', 2: 'interested', 3: 'not_interested',4: 'have', 5: 'bitfield', 6: 'request', 7: 'piece'}
        msg_name = message_types.get(type, f'unknown({type})')
        if type != 'keep_alive':
            print(f"[{self.ip}:{self.port}] Received: {msg_name}")
        
        if type == 'keep_alive':
            pass
        elif type == 0:  #choke
            self.peer_choking = True
            print(f"[{self.ip}:{self.port}] Peer is choking us")
        elif type == 1:  # unchoke
            self.peer_choking = False
            print(f"[{self.ip}:{self.port}] Peer unchoked us - requesting pieces")
            self.ask_pieces()
        elif type == 2:  # interested
            self.peer_interest = True
            print(f"[{self.ip}:{self.port}] Peer is interested - unchoking them")
            self.unchoke()
        elif type == 3:  #not interested
            self.peer_interest = False
        elif type == 4:  #have
            piece_index = struct.unpack('>I', payload)[0]
            if self.peer_bit_field is None:
                self.peer_bit_field = [False]*self.manager.num_pieces
            if piece_index < len(self.peer_bit_field):
                self.peer_bit_field[piece_index] = True
                print(f"[{self.ip}:{self.port}] Peer has piece {piece_index}")
        elif type == 5:  #bitfield
            self.peer_bit_field = self.parse_bit_field(payload)
            has_pieces = sum(self.peer_bit_field)
            print(f"[{self.ip}:{self.port}] Received bitfield: {has_pieces}/{len(self.peer_bit_field)} pieces")
            if not self.peer_choking:
                self.ask_pieces()
        elif type == 6: # request
            print(f"[{self.ip}:{self.port}] Peer requesting piece from us")
            self.handle_request(payload)
        elif type == 7:  # piece
            print(f"[{self.ip}:{self.port}] Received piece data")
            self.handle_piece(payload)
    def parse_bit_field(self, bit_field):
        bits =[]
        for byte in bit_field:
            for i in range(8):
                bits.append((byte >> (7-i)) & 1 == 1)
        return bits[:self.manager.num_pieces]
    def send_message(self, type, payload = b''):
        try:
            length = len(payload) + 1
            message = struct.pack('>I', length) + struct.pack('B', type) + payload
            self.socket.send(message)
        except Exception as error:
            print(f'Error sending message to ip={self.ip}:port={self.port} ')
            print(f'Error: {error}')
    def keep_alive(self):
        try:
            self.socket.send(struct.pack('>I',0))
        except Exception as error: 
            pass
    def send_bit_field(self):
        bit_field = self.manager.get_bit_field()
        print(f"[{self.ip}:{self.port}] Sending bitfield: {len(bit_field)} bytes")
        has_pieces = sum(self.manager.piece_status)
        print(f"[{self.ip}:{self.port}] We have {has_pieces}/{self.manager.num_pieces} pieces")
        self.send_message(5, bit_field)

    def send_interested(self):
        self.interest = True
        self.send_message(2)
    def unchoke(self):
        self.choking = False
        self.send_message(1)
    def have(self, index):
        payload = struct.pack('>I',index)
        self.send_message(4, payload)
    def ask_pieces(self):
        if self.peer_choking:
            print(f"[{self.ip}:{self.port}] Can't request - peer is choking us")
            return
        
        if self.peer_bit_field is None:
            print(f"[{self.ip}:{self.port}] Can't request - no bitfield received yet")
            return
        
        requested = 0
        max_concurrent = 3
        
        for index in range(self.manager.num_pieces):
            we_have = self.manager.have(index)
            peer_has = self.peer_bit_field[index]
            already_requested = self.manager.is_piece_requested(index)
            
            if not we_have and peer_has and not already_requested:
                print(f"[{self.ip}:{self.port}] Requesting piece {index}")
                self.manager.mark_piece(index)
                self.request(index)
                requested += 1
                
                if requested >= max_concurrent:
                    break
        
        if requested == 0:
            # Debug why we couldn't request anything
            pieces_we_need = sum(1 for i in range(self.manager.num_pieces) if not self.manager.have(i))
            pieces_peer_has = sum(1 for i in range(self.manager.num_pieces) if self.peer_bit_field[i])
            pieces_already_requested = sum(1 for i in range(self.manager.num_pieces) if self.manager.is_piece_requested(i))
            
            print(f"[{self.ip}:{self.port}] No pieces to request:")
            print(f"  - We need: {pieces_we_need}/{self.manager.num_pieces}")
            print(f"  - Peer has: {pieces_peer_has}/{self.manager.num_pieces}")
            print(f"  - Already requested: {pieces_already_requested}/{self.manager.num_pieces}")


    def request(self, index):
        p_size = self.manager.get_size(index)
        b_size = 16384
        for off in range(0, p_size, b_size):
            length = min(b_size, p_size-off)
            payload = struct.pack('>III', index, off,length)
            self.send_message(6, payload)
    def handle_request(self, payload):
        if self.choking:
            return
        index, off, length = struct.unpack('>III', payload)
        if not self.manager.have(index):
            return
        data = self.manager.get_data(index)
        block = data[off:off+length]
        payload = struct.pack('>II', index, off)+block
        self.send_message(7, payload)
    def handle_piece(self, payload):
        block = payload[8:]
        index, off = struct.unpack('>II', payload[:8])
        if self.manager.add_block(index, off, block):
            print(f'Downloaded the piece index: {index}')
            self.client.broadcast_have(index)
            self.ask_pieces()
    def close(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
class PieceManager:
    def __init__(self, torrent_file, output_path):
        self.torrent = torrent_file
        self.output_path = output_path
        self.num_pieces = torrent_file.num_pieces()
        self.pieces = [None] * self.num_pieces
        self.piece_status = [False] * self.num_pieces
        self.piece_requested = [False] * self.num_pieces
        self.blocks_received = [set() for _ in range(self.num_pieces)]
        self.lock = threading.Lock()
        self.file_handle = None
        if not os.path.exists(output_path):
            print(f"Creating new file: {output_path}")
            self.file_handle = open(output_path, 'wb')
            self.file_handle.seek(torrent_file.file_length() - 1)
            self.file_handle.write(b'\0')
            self.file_handle.close()
        else:
            print(f"File already exists, opening in r+b mode: {output_path}")
        self.file_handle = open(output_path, 'r+b')
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
    def add_block(self, index, off, block):
        with self.lock:
            if self.pieces[index] is None:
                p_size = self.torrent.get_piece_size(index)
                self.pieces[index] = bytearray(p_size)
            
            end_offset = off +len(block)
            print(f"  Adding block to piece {index}: offset {off}-{end_offset}, size {len(block)}")
            self.pieces[index][off:off+len(block)] = block
            self.blocks_received[index].add(off)
            if self.is_complete(index):
                print(f"  Piece {index} is complete, verifying...")
                return self.verify_save(index)
            else:
                received_blocks = len(self.blocks_received[index])
                total_blocks = self.get_total_blocks(index)
                print(f"  Piece {index} partial: {received_blocks}/{total_blocks} blocks")
        return False
    def get_total_blocks(self, index):
        piece_size = self.get_size(index)
        block_size = 16384
        return (piece_size + block_size - 1)//block_size
    def is_complete(self, index):
        if self.pieces[index] is None:
            return False
        
        total_blocks = self.get_total_blocks(index)
        received_blocks = len(self.blocks_received[index])
        return received_blocks == total_blocks
    def verify_save(self, index):
        piece_data = bytes(self.pieces[index])
        piece_hash = hashlib.sha1(piece_data).digest()
        expected = self.torrent.get_piece_hash(index)
        print(f"\nVerifying complete piece {index}:")
        print(f"  Size: {len(piece_data)} bytes")
        print(f"  Hash: {piece_hash.hex()}")
        print(f"  Expected: {expected.hex()}")
        
        if piece_hash == expected:
            print(f"  ✓ VERIFICATION SUCCESS!")
            off = index * self.torrent.piece_length()
            self.file_handle.seek(off)
            self.file_handle.write(piece_data)
            self.file_handle.flush()
            self.piece_status[index] = True
            self.piece_requested[index] = False
            # Clear blocks tracking for this piece
            self.blocks_received[index].clear()
            return True
        else:
            print(f"  ✗ VERIFICATION FAILED!")
            self.pieces[index] = None
            self.piece_requested[index] = False
            # Clear blocks tracking to allow re-download
            self.blocks_received[index].clear()
            return False
    def get_data(self, index):
        with self.lock: 
            if not self.piece_status[index]:
                return None
            off = index * self.torrent.piece_length()
            piece_size = self.get_size(index)
            self.file_handle.seek(off)
            return self.file_handle.read(piece_size)
    def get_bit_field(self):
        with self.lock:
            bit_field = bytearray((self.num_pieces+7)//8)
            for i, h in enumerate(self.piece_status):
                if h: 
                    byte_idx= i // 8
                    bit_idx = 7-(i%8)
                    bit_field[byte_idx] |= (1 << bit_idx)
            return bytes(bit_field)
    def complete(self):
         with self.lock:
            return all(self.piece_status)
    def progress(self):
        with self.lock:
            return sum(self.piece_status) / self.num_pieces * 100
    def close(self):
        if self.file_handle:
            self.file_handle.close()

class BitTorrentClient:
    def __init__(self, torrent_path, output_path = None):
        self.torrent = None
        self.torrent_path=torrent_path
        self.output_path = output_path
        self.peer_id = self.generate_peer_id()
        self.piece_manager = None
        self.peers =[]
        self.peer_lock = threading.Lock()
        self.port = 6881
        self.server_socket = None
        self.running = False
    def generate_peer_id(self):
        return b'-PC0001-' + ''.join([str(random.randint(0, 9)) for _ in range(12)]).encode()
    
    def start(self):    
        from Torrent import Torrent    
        print(f"Loading torrent file: {self.torrent_path}")
        self.torrent = Torrent(self.torrent_path)
        if self.output_path:
            output_path = self.output_path
        else:
            output_path = self.torrent.file_name()
        print(f"Output file: {output_path}")
        print(f"File size: {self.torrent.file_length()} bytes")
        print(f"Pieces: {self.torrent.num_pieces()}")
        
        # Track if file was newly created
        file_existed = os.path.exists(output_path)
        
        self.piece_manager = PieceManager(self.torrent, output_path)
        
        # Only verify if file existed before AND has correct size
        if file_existed:
            file_size = os.path.getsize(output_path)
            if file_size == self.torrent.file_length():
                print("File already exists with correct size - verifying pieces...")
                self.verify_existing_file()
            else:
                print(f"File exists but has wrong size ({file_size} vs {self.torrent.file_length()}) - will download")
        else:
            print("New file created - ready to download")
        
        self.start_server()
        peers = self.contact_tracker('started')
        if not peers:
            print("No peers received from tracker")
            return
        
        print(f"Received {len(peers)} peers from tracker")
        self.connect_to_peers(peers)
        self.monitor_progress()

    def verify_existing_file(self):
        try:
            with open(self.piece_manager.output_path, 'rb') as f:
                for index in range(self.piece_manager.num_pieces):
                    piece_size = self.torrent.get_piece_size(index)
                    offset = index * self.torrent.piece_length()
                    f.seek(offset)
                    piece_data = f.read(piece_size)
                    
                    piece_hash = hashlib.sha1(piece_data).digest()
                    expected_hash = self.torrent.get_piece_hash(index)
                    
                    # DEBUG: Print hash comparison
                    print(f"Piece {index}:")
                    print(f"  Size: {len(piece_data)} bytes (expected: {piece_size})")
                    print(f"  Computed hash: {piece_hash.hex()}")
                    print(f"  Expected hash: {expected_hash.hex()}")
                    
                    if piece_hash == expected_hash:
                        with self.piece_manager.lock:
                            self.piece_manager.piece_status[index] = True
                        print(f"  ✓ Verified piece {index}")
                    else:
                        print(f"  ✗ Piece {index} verification FAILED")
            
            verified_count = sum(self.piece_manager.piece_status)
            print(f"\nVerified {verified_count}/{self.piece_manager.num_pieces} pieces")
            
            if self.piece_manager.complete():
                print("This peer has the complete file and will act as a seeder!")
        except Exception as e:
            print(f"Error verifying existing file: {e}")
            import traceback
            traceback.print_exc()
    def start_server(self):
        def server_thread():
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                port = 6881
                max_attempts = 10
                for attempt in range(max_attempts):
                    try:
                        self.server_socket.bind(('0.0.0.0', port))
                        break
                    except OSError:
                        port = 6881 + attempt + 1
                        if attempt == max_attempts - 1:
                            raise
                
                self.port = port  # Store the actual port we're using
                self.server_socket.listen(5)
                print(f"Server listening on port {port}")
                
                while self.running:
                    try:
                        self.server_socket.settimeout(1)
                        client_socket, address = self.server_socket.accept()
                        threading.Thread(target=self.handle_incoming_peer, 
                                    args=(client_socket, address), 
                                    daemon=True).start()
                    except socket.timeout:
                        continue
                    except Exception as e:
                        break
            except Exception as e:
                print(f"Server error: {e}")
        
        self.running = True
        threading.Thread(target=server_thread, daemon=True).start()
        time.sleep(0.5) 
    def handle_incoming_peer(self, client_socket, address):
        try:
            print(f"Incoming connection from {address}")
            
            # Receive handshake
            response = client_socket.recv(68)
            if len(response) < 68:
                client_socket.close()
                return
                
            # Verify info hash
            receive_info = response[28:48]
            if receive_info != self.torrent.info:
                print(f"Invalid info hash from {address}")
                client_socket.close()
                return
            
            # Extract peer_id
            peer_id = response[48:68]
            
            # Send our handshake back
            protocol = b'BitTorrent protocol'
            msg = struct.pack('B', len(protocol)) + protocol + b'\x00'*8 + self.torrent.info + self.peer_id
            client_socket.send(msg)
            
            # Create peer object for this incoming connection
            ip, port = address
            peer = Peer(ip, port, self.torrent.info, self.peer_id, self, self.piece_manager)
            peer.socket = client_socket  # Use existing socket
            peer.running = True
            
            # Start peer thread
            peer.thread = threading.Thread(target=peer.run, daemon=True)
            peer.thread.start()
            
            with self.peer_lock:
                self.peers.append(peer)
                
            print(f"Successfully established incoming connection from {address}")
        except Exception as e:
            print(f"Error handling incoming peer from {address}: {e}")
            try:
                client_socket.close()
            except:
                pass
    def contact_tracker(self, event):
        info_hash_ed = ''.join(f'%{byte:02x}' for byte in self.torrent.info)
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
            announcement = self.torrent.announce()
            if isinstance(announcement, bytes):
                announcement = announcement.decode('utf-8')

            url = announcement + '?info_hash='+info_hash_ed+ "&"+ urlencode(params)
            print(f"\n=== Contacting Tracker ===")
            print(f"URL: {url}")
            print(f"Info hash: {info_hash_ed}")
            response = requests.get(url, timeout=10)
            print(f"Response status code: {response.status_code}")
            print(f"Response content: {response.content[:200]}")
            if response.status_code == 200:
                decoded = bdecode(response.content)
                print(f"Decoded response: {decoded}")
                peers = decoded.get('peers',[])
                print(f"Number of peers found: {len(peers)}")
                print(f"Peers: {peers}")
                return peers
            
        except Exception as error:
            print(f"Error contacting tracker: {error}")
            traceback.print_exc()
        
        return []
    
    def connect_to_peers(self, peer_list):
        for peer_info in peer_list[:5]: 
            try:
                ip = peer_info.get('ip', '')
                if isinstance(ip,bytes):
                    ip = ip.decode('utf-8')
                port = peer_info.get('port', 0)
                peer_id = peer_info.get('peerid', b'')
                if peer_id == self.peer_id:
                    print(f"Skipping itself (peer id: {peer_id})")
                    continue
                if ip and port:
                    peer = Peer(ip, port, self.torrent.info, self.peer_id, self, self.piece_manager)
                    if peer.connect():
                        with self.peer_lock:
                            self.peers.append(peer)
                            print(f"Connected to peer at {ip}:{port}")
            except Exception as error:
                print(f"Error connecting to peer: {error}")
    
    def broadcast_have(self, index):
        with self.peer_lock:
            for peer in self.peers:
                peer.have(index)
    
    def monitor_progress(self):
        if self.piece_manager.complete():
            print("This peer is a complete seeder. Staying online to serve other peers...")
            print("Press Ctrl+C to stop seeding.")
            try:
                while True:
                    time.sleep(5)
                    with self.peer_lock:
                        active_peers = len(self.peers)
                    print(f"Seeding... ({active_peers} connected peers)")
            except KeyboardInterrupt:
                print("\nStopping seeder...")
                self.cleanup()
            return
        
        # If we don't have complete file, monitor download progress
        while not self.piece_manager.complete():
            time.sleep(5)
            progress = self.piece_manager.progress()
            with self.peer_lock:
                active_peers = len(self.peers)
            print(f"Progress: {progress:.2f}% ({active_peers} peers)")
        
        print("Download complete!")
        
        # After download completes, ask if user wants to keep seeding
        print("\nDownload finished! Do you want to keep seeding? (yes/no): ", end='', flush=True)
        try:
            response = input().lower()
            if response == 'yes':
                self.contact_tracker('completed')
                print("Seeding... Press Ctrl+C to stop.")
                while True:
                    time.sleep(5)
                    with self.peer_lock:
                        active_peers = len(self.peers)
                    print(f"Seeding... ({active_peers} connected peers)")
            else:
                self.contact_tracker('completed')
                self.cleanup()
        except KeyboardInterrupt:
            print("\nStopping...")
            self.contact_tracker('stopped')
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


def main():
    if len(sys.argv) < 2:
        print("Use: python peer.py <torrent_file> [output_file_path]")
        sys.exit(1)
    
    torrent_file = sys.argv[1]
    
    if not os.path.exists(torrent_file):
        print(f"Torrent file not found: {torrent_file}")
        sys.exit(1)
    
    # Allow specifying custom output file via command line
    custom_output = sys.argv[2] if len(sys.argv) > 2 else None
    
    if custom_output:
        print(f"Using custom output file: {custom_output}")
        client = BitTorrentClient(torrent_file, custom_output)
        client.start()
        return
    
    # Load torrent to get original filename
    from Torrent import Torrent
    temp_torrent = Torrent(torrent_file)
    original_filename = temp_torrent.file_name()
    
    if os.path.exists(original_filename):
        print(f"\nFound existing file: {original_filename}")
        response = input("Do you want to seed this file? (yes/no): ").lower()
        
        # FIXED LOGIC HERE:
        if response == 'yes':  # User wants to SEED existing file
            # Use the existing file
            client = BitTorrentClient(torrent_file, original_filename)
        else:  # User wants to DOWNLOAD to new file
            # Create new timestamped filename
            timestamp = int(time.time())
            new_filename = f"downloaded_{timestamp}_{original_filename}"
            print(f"Will download to: {new_filename}")
            client = BitTorrentClient(torrent_file, new_filename)
    else:
        # File doesn't exist, download normally
        client = BitTorrentClient(torrent_file, original_filename)
    
    client.start()




if __name__ == '__main__':
    main()