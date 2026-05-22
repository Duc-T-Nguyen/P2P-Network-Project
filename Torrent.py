import hashlib
import os
from Bencode import bencode, bdecode


class Torrent:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = None
        self.info = None
        self.parse()

    def parse(self):
        with open(self.file_path, 'rb') as f:
            self.data = bdecode(f.read())
        info_b = bencode(self.data['info'])
        self.info = hashlib.sha1(info_b).digest()

    def announce(self):
        announcement = self.data.get('announce', '')
        if isinstance(announcement, bytes):
            return announcement.decode('utf-8')
        return announcement

    def announcement_list(self):
        return self.data.get('announce-list', [[self.announce()]])

    def file_name(self):
        name = self.data['info'].get('name', 'downloaded_file')
        if isinstance(name, bytes):
            return name.decode('utf-8')
        return name

    def is_multi_file(self):
        """Return True if this torrent contains multiple files."""
        return 'files' in self.data['info']

    def files(self):
        """
        Returns a list of dicts for every file in the torrent:
            [{'path': 'subdir/file.txt', 'length': 12345, 'offset': 0}, ...]
        For a single-file torrent the list has exactly one entry.
        """
        info = self.data['info']
        if self.is_multi_file():
            result = []
            offset = 0
            base = self.file_name()
            for f in info['files']:
                path_parts = f['path']
                # path parts may be bytes
                decoded_parts = [
                    p.decode('utf-8') if isinstance(p, bytes) else p
                    for p in path_parts
                ]
                rel_path = os.path.join(base, *decoded_parts)
                length = f['length']
                result.append({
                    'path': rel_path,
                    'length': length,
                    'offset': offset,
                })
                offset += length
            return result
        else:
            return [{
                'path': self.file_name(),
                'length': info['length'],
                'offset': 0,
            }]

    def file_length(self):
        """Total byte length across all files."""
        info = self.data['info']
        if 'length' in info:
            return info['length']
        return sum(f['length'] for f in info['files'])

    def piece_length(self):
        return self.data['info']['piece length']

    def pieces(self):
        pieces = self.data['info']['pieces']
        if isinstance(pieces, str):
            pieces = pieces.encode('latin-1')
        return [pieces[i:i + 20] for i in range(0, len(pieces), 20)]

    def num_pieces(self):
        return len(self.pieces())

    def get_piece_hash(self, index):
        if index < 0 or index >= self.num_pieces():
            raise IndexError(f'Index Error with Piece index: {index}')
        return self.pieces()[index]

    def get_piece_size(self, index):
        if index < 0 or index >= self.num_pieces():
            raise IndexError(f'Index Error with Piece index: {index}')
        if index == self.num_pieces() - 1:
            remainder = self.file_length() % self.piece_length()
            if remainder > 0:
                return remainder
        return self.piece_length()

    def __str__(self):
        return (
            f'Torrent(name={self.file_name()}, '
            f'total_length={self.file_length()}, '
            f'files={len(self.files())}, '
            f'pieces={self.num_pieces()})'
        )

    def __repr__(self):
        return self.__str__()