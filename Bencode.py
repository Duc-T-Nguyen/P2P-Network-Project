
def bencode(data): # encode it to ben format reference Final report to see what bencode is generally suposed to do
    if isinstance(data, int):
        return b'i' + str(data).encode() + b'e'
    elif isinstance(data, bytes):
        return str(len(data)).encode() + b':' + data
    elif isinstance(data, str):
        return bencode(data.encode('utf-8'))
    elif isinstance(data, list):
        return b'l' + b''.join(bencode(item) for item in data) + b'e'
    elif isinstance(data, dict):
        items = []
        sorted_keys = sorted(data.keys(), key=lambda k: k.encode('utf-8') if isinstance(k, str) else k)
        for key in sorted_keys:
            if isinstance(key, str):
                encoded_key = bencode(key.encode('utf-8'))
            else:
                encoded_key = bencode(key)
            
            items.append(encoded_key)
            items.append(bencode(data[key]))
        return b'd' + b''.join(items) + b'e'
    else:
        raise TypeError(f"Cannot bencode type {type(data)}")

def bdecode(data):
    def decode_next(data, index):
        if data[index:index+1] == b'i':
            end = data.index(b'e', index)
            return int(data[index+1:end]), end + 1
        elif data[index:index+1] == b'l':
            result = []
            index += 1
            while data[index:index+1] != b'e':
                item, index = decode_next(data, index)
                result.append(item)
            return result, index + 1
        elif data[index:index+1] == b'd':
            result = {}
            index += 1
            while data[index:index+1] != b'e':
                key, index = decode_next(data, index)
                value, index = decode_next(data, index)
                if isinstance(key, bytes):
                    try:
                        key = key.decode('utf-8')
                    except:
                        pass # keep as bytes if the decoding fails in some way
                result[key] = value
            return result, index + 1
        elif data[index:index+1].isdigit():
            colon = data.index(b':', index)
            length = int(data[index:colon])
            start = colon + 1
            end = start + length
            return data[start:end], end
        else:
            raise ValueError(f"Invalid bencode data at index {index}")
    result, _ = decode_next(data, 0)
    return result
