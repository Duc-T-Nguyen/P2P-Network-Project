
import hashlib
import os
import sys
from Bencode import bencode

def create_torrent(file_path, tracker_url='http://localhost:3000/announce', piece_length=262144):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found")
        return None
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    print(f"Creating torrent for: {file_name}")
    print(f"File size: {file_size} bytes")
    print(f"Piece length: {piece_length} bytes")
    print(f"Tracker URL: {tracker_url}")
    pieces = b''
    with open(file_path, 'rb') as f:
        while True:
            piece = f.read(piece_length)
            if not piece:
                break
            piece_hash = hashlib.sha1(piece).digest()
            pieces += piece_hash
    num_pieces = len(pieces)// 20
    print(f"Number of pieces: {num_pieces}")
    torrent_data ={
        'announce': tracker_url,
        'info':{
            'name': file_name,
            'piece length': piece_length,
            'pieces': pieces,
            'length': file_size,
        }
    }
    encoded_data = bencode(torrent_data)
    torrent_filename = file_name + '.torrent'
    with open(torrent_filename, 'wb') as f:
        f.write(encoded_data)
    print(f"\n Torrent file created: {torrent_filename}")
    info_encoded = bencode(torrent_data['info'])
    info_hash = hashlib.sha1(info_encoded).digest()
    print(f"Info hash: {info_hash.hex()}")
    return torrent_filename
def create_TestFile(filename='TestFile.txt', size_kb=100):
    print(f"\nCreating test file: {filename} ({size_kb}KB)")
    with open(filename, 'wb') as f:
        content = b'This is a test file for BitTorrent testing.\n'
        content += b'=' * 50 + b'\n'
        bytes_written = len(content)
        target_size = size_kb * 1024
        
        pattern = b'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' * 100
        while bytes_written < target_size:
            chunk_size = min(len(pattern), target_size - bytes_written)
            f.write(pattern[:chunk_size])
            bytes_written += chunk_size
    print(f"✓ Test file created: {filename}")
    return filename
def main():
    if len(sys.argv) < 2:
        print("No file specified. Creating a test file...")
        TestFile = create_TestFile('TestFile.txt', 100)
        tracker_url = 'http://localhost:3000/announce'
    else:
        TestFile = sys.argv[1]
        tracker_url = sys.argv[2] if len(sys.argv) > 2 else 'http://localhost:3000/announce'
    torrent_file = create_torrent(TestFile, tracker_url)
    
    if torrent_file:
        print(f"\n{'='*60}")
        print("Next steps:")
        print(f"1. Make sure your tracker is running on {tracker_url}")
        print(f"2. Start a seeder using the command in the terminal: python3 peer.py {torrent_file}")
        print(f"3. Start more peers in other terminals to download")
        print(f"4. Check tracker stats with the command: curl http://localhost:3000/stats")
        print('='*60)

if __name__ == '__main__':
    main()