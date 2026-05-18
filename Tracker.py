import time 
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer 
import json
from urllib.parse import urlparse, parse_qs
from Bencode import bencode, bdecode
import sys

class TrackerData:
    def __init__(self, timeout=180):
        self.torrents={}
        self.lock = threading.Lock()
        self.timeout= timeout
    def create_peers(self,info,peerid, ip, port, event=None):
        with self.lock: 
            if info not in self.torrents: 
                self.torrents[info]={}
            if event == 'stopped':
                if peerid in self.torrents[info]:
                    del self.torrents[info][peerid]
            else: 
                 self.torrents[info][peerid] = {
                'peerid': peerid,
                'ip': ip,
                'port': port,
                'event':event,
                'last_time': time.time(),
            }
    def get_peer(self,info,peerid):
        with self.lock:
            if info not in self.torrents:
                return []
            
            peers=[]
            for peer_id, peerinfo in self.torrents[info].items():
                peers.append({
                    'peerid': peer_id,
                    'port':peerinfo['port'],
                    'ip': peerinfo['ip'],
                })
            return peers
    def cleanup_old(self):
        with self.lock:
            curtime = time.time()
            for info in list(self.torrents.keys()):
                for peerid in list(self.torrents[info].keys()):
                    if curtime - self.torrents[info][peerid]['last_time']>self.timeout:
                        print(f'Remove peer: {peerid} because of timeout')
                        del self.torrents[info][peerid]

    def status(self):
        with self.lock:
            status_info = {}
            for info, peers in self.torrents.items():
                key = info.hex() if isinstance(info, bytes) else str(info)
                status_info[key] = {
                    'Num_peers': len(peers),
                    'Peers': list(peers),
                }
            return status_info
class TrackerRequest(BaseHTTPRequestHandler):

    tracker_data = None

    def do_GET(self):
        self.get_request()
    def error(self,code, message):
        self.send_response(code)
        self.send_header("Content-Type", 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))
    def get_request(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == '/announce':
            self.announce(parsed_url)
        elif parsed_url.path == '/stats':
            self.stats(parsed_url)
        elif parsed_url.path == '/error':
            self.error(404, 'Error, Not Found')
    def announce(self, parsed_url):
        try:
            from urllib.parse import unquote_to_bytes
            
            query_params = {}
            if parsed_url.query:
                for param in parsed_url.query.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        query_params[key] = unquote_to_bytes(value)
            peerid = query_params.get('peer_id', b'')
            info = query_params.get('info_hash', b'')
            port = int(query_params.get('port', b'0').decode('utf-8'))
            event = query_params.get('event', b'').decode('utf-8') if query_params.get('event') else ''
            
            ip = self.client_address[0]
            print(f"Announce from peer: {peerid[:20]}, info_hash: {info.hex()[:20]}...")
            
            self.tracker_data.create_peers(info, peerid, ip, port, event)
            peers = self.tracker_data.get_peer(info, peerid)

            response = {
                'interval': 60,
                'peers': peers,
            }
            
            result_data = bencode(response)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(result_data))
            self.end_headers()
            self.wfile.write(result_data)
            
            print(f"Sent {len(peers)} peers to requesting client")
        except Exception as error:
            print(f"Error in announce request: {error}")
            import traceback
            traceback.print_exc()
            self.error(500, str(error))
    def stats(self, parsed_url):
        try:
            stats = self.tracker_data.status()
            result = json.dumps(stats, indent=1)
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length', len(result))
            self.end_headers()
            self.wfile.write(result.encode('utf-8'))
        except Exception as error:
            print(f"Error in status request: {error}" )
            self.error(500, str(error))
    def log_message(self, format, *args): 
        pass
class TrackerServer:
    def __init__(self,host, port):
        self.host = host
        self.port = port
        self.tracker_data = TrackerData()
        self.server = None
        self.cleanup = None
        self.run = False
    def start(self):
        TrackerRequest.tracker_data = self.tracker_data
        self.server = HTTPServer((self.host, self.port), TrackerRequest)
        self.run = True
        self.cleanup_thread = threading.Thread(target=self.cleanup_loop, daemon=True)
        self.cleanup_thread.start()


        print(f'Tracker started on host: {self.host} port:{self.port}')
        print(f'Announce url: http://{self.host}:{self.port}/announce')
        print(f'Status url: http://{self.host}:{self.port}/stats')
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print('Stopping tracker')
            self.stop()
    def stop(self):
        self.run = False
        if self.server:
            self.server.shutdown()
    def cleanup_loop(self):
        while self.run: 
            time.sleep(30)
            self.tracker_data.cleanup_old()
def main():
    port = 3000
    host = '0.0.0.0'
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid Port: {sys.argv[1]}")
            sys.exit(1)
    tracker = TrackerServer(host=host,port=port)
    tracker.start()
    
if __name__ == '__main__':
    main()
