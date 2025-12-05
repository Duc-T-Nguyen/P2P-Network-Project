import hashlib
from Bencode import bencode,bdecode
class Torrent:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = None
        self.info = None
        self.parse()
    def parse(self):
        with open(self.file_path, 'rb') as file_name:
            self.data = bdecode(file_name.read())
        info_b = bencode(self.data['info'])
        self.info= hashlib.sha1(info_b).digest()
    def announce(self):
        announcement = self.data.get('announce','')
        if isinstance(announcement, bytes):
            return announcement.decode('utf-8')
        return announcement
    def announcement_list(self):
        return self.data.get('announcement-list',[[self.announce]])
    def file_name(self):
        name = self.data['info'].get('name','downloaded_file')
        if isinstance(name, bytes):
            return name.decode('utf-8')
        return name
    def file_length(self):
        info=self.data['info']
        if 'length' in info:
            return info['length']  
        else:
            return sum(file['length'] for file in info['files'])
    def piece_length(self):
        return self.data['info']['piece length']
    def pieces(self):
        pieces = self.data['info']['pieces']
        if isinstance(pieces, str):
            pieces = pieces.encode('latin-1')
        return [pieces[i:i+20] for i in range(0,len(pieces),20)]
    def num_pieces(self):
        return len(self.pieces()) 
    def get_piece_hash(self, index):
        if index < 0 or index >= self.num_pieces():
            raise IndexError(f'Index Error with Piece index: {index}')
        return self.pieces()[index]
    def get_piece_size(self, index):
        if index < 0 or index >= self.num_pieces():
            raise IndexError(f'Index Error with Piece index: {index}')
        if index == self.num_pieces()-1:
            remainder =self.file_length()%self.piece_length()
            if remainder > 0:
                return remainder
            else:
                return self.piece_length()
        return self.piece_length()
    def __str__(self):
        return (f'Torrent File ( file_name = {self.file_name()}, file_length = {self.file_length()}, pieces = {self.pieces()})'
)
    def __repr__(self):
        return self.__str__()


