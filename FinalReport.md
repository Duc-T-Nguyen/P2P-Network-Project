Project Overview: 

- This P2P project implements a simple BitTorrent like peer-to-peer file sharing client. The project is designed to allow distributed file sharing, including a tracker server, torrent file creation method, and peer clients that are able to both seed and download files.

Framework Implementation and Architecture:

- Bencode.py:
    - The Bencode.py file implements a bencode format for serializing Python data structures. I attempted to implement as best I could what I saw was the necessary components of Bencode to store and transmitt structured data between peers. The Bencode.py file is designed to encode integers, bytes, Strings, lists, and dictionaries. Furthermore, the python script is able to take bencode format and decode the format back into Python objects. The Bencode.py script is important for parsing torrent files and tracker communication.
- Torrent.py:
    - The Torrent.py script parses '.torrent' files using bencode and extracts metadata like: the announce url (called announcement), file name, and piece hashes through its methods. Furthermore, Torrent.py calculate SHA-1 info hash for tracker identification and provides for piece management.
- Tracker.py:
    - Tracker.py is a tracker for finding peers in the network and manages peer creation and removal. The Tracker.py provides a 'anounce' and 'stats' endpoint to register/create peers and monitor active torrents respectively. When we have stale peer connections the Tracker.py automatically cleans up these peer connections.
- CreateTorrent.Py:
    - This python script creates a '.torrent' file from local files. If the file path does not exist in the OS, then the script will report a error but otherwise retrieve the file size and name alongside reporting back to the user info about the file. The file creates test files for testing and outputs hash info for verification.
- Peer.py:
    - The Peer.py file is divided into multiple class sections: BitTorrentClient, PieceManager, and Peer. The BitTorrentClient class is responsible for downloads and uploads between peers in the network through its methods. PieceManager is a class to manage pieces such as its storage, verification (ex: verify_save(self, index)), and tracks blocks and their sizes throught methods like add_block and get_total_blocks. The Peer class at the start of the file handles the P2P connections and BitTorrent protocol messages. The Peer class also has messages for choking, requests, bitfields, etc.

Instructions to Run Project: 
- Note that I put in python3 for the commands because i use a macos but if you want to execute these commands on non macs you have to use python
Tracker.py 
    - To start the Tracker Server in the Tracker.py file with its default port of 3000:
        - execute command:
            - python3 Tracker.py 
    - To execute with a special port:
        - execute command:
            - python3 Tracker.py (port number)

    - The result if you execute with its default port:
        Tracker started on host: 0.0.0.0 port:3000
        Announce url: http://localhost:3000/announce
        Status url: http://localhost:3000/stats

Torrent.py:
    - To Create a Torrent File (this creates a generic txt and Torrent file: TestFile.txt and TestFile.txt.torrent): 
        - python3 CreateTorrent.py
    - You can also create a file or designate a existing file to by specifying the path 
        - python3 CreateTorrent.py /path/to/file http://tracker.example.com:3000/announce
        - python3 CreateTorrent.py /path/to/file 

    - Example output with TestFile.txt: 
        Creating torrent for: TestFile.txt
        File size: 102400 bytes
        Piece length: 262144 bytes
        Number of pieces: 1
        Torrent file created: TestFile.txt.torrent
        Info hash: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
Peer.py:

    - To initiate the Seeder with generic file:
        - python3 Peer.py TestFile.torrent
    - To initiate with special output path: 
        python3 Peer.py TestFile.torrent ./downloads/filename
If you want to monitor the tracker status: 
    - curl http://localhost:3000/stats | python3 -m json.tool

to create two process to connect with each other only and download respond yes to the first prompt in seeding the file in Peer.py: Do you want to seed this file? (yes/no): yes and on the second response no
 Example: 
# Terminal 1: Start tracker
python3 Tracker.py 3000

# Terminal 2: Create torrent
python3 CreateTorrent.py TestFile.txt

# Terminal 2 : Start seeder
python3 Peer.py TestFile.txt.torrent

# Terminal 3: Start leecher
python3 Peer.py TestFile.txt.torrent downloaded_TestFile.txt

# Terminal 4: Monitor tracker
watch -n 5 'curl -s http://localhost:3000/stats | python3 -m json.tool'

Command Line Options:

Tracker.py: 
    Port: python3 Tracker.py 8080 (start tracker on custom port)
CreateTorrent.py: 
    Create Testfile and Torrent: python3 CreateTorrent.py

    File: python3 CreateTorrent.py file.txt (create torrent from file)

    File_url : python3 CreateTorrent.py file.txt http://tracker:3000/announce (custom tracker url)

Peer.py:

    torrent: python3Peer.py file.torrent (start client with torrent)

    torrent output: python3 Peer.py file.torrent output.txt (custom output file name)
Protocol Details
BitTorrent Protocol Messages
0: Choke
1: Unchoke
2: Interested
3: Not Interested
4: Have
5: Bitfield
6: Request
7: Piece
