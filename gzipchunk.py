import struct
import zlib
import ctypes
import ctypes.util

# This seems to be the only way of getting to zlib's
# crc32_combine function. N.B. I know this works on
# Debian Linux. It probably works on other Linux
# distros. Windows & MacOS? No idea.
ctypes_zlib = ctypes.CDLL(ctypes.util.find_library('z'))
ctypes_zlib.crc32_combine.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
ctypes_zlib.crc32_combine.restype = ctypes.c_ulong

class GzipChunk:
    """
    This class allows you to construct a gzipped object in stages.
    Once created, you can use the "add" mehod to add strings or 
    byte arrays to the object. The "output" method will return a
    byte array containing the gzipped content.

    So far, that's nothing special. But the "add" method can also
    take a GzipChunk object, so long as that object itself hasn't
    had a GzipChunk object added to *it*. When "add" is called
    with such an object, the compressed data from the added object
    is added to the current object and, on calling the "output" method,
    you'll still end up with a valid gzip data stream.

    So what's the use of this?

    Imagine you have a large chunk of static data which you want to 
    add, inline, to many dynamically generated files, with the 
    intention of the result being a compressed stream. If you add
    the data to each plaintext and then compress, you'll end up 
    compressing the data static data many times over. If, instead,
    you compress the static data using a GzipChunk object, then 
    add *that* to the other objects as you compress them, then you'll
    only have compressed the static data once.

    Still confused?

    OK, I'll fess up. The general idea for this is to generate a vast
    collection of compressed web pages for abusive web crawlers to chew
    on. I'd like, sometimes, to plonk a zip bomb into generated pages: 
    a chunk of HTML that decompresses to several MBytes of data. But 
    generating it from raw text, on the fly, eats more of my CPU than 
    the crawler will need to decompress. 

    If I can pre-compress a large chunk of data once and insert that into
    thousands of dynamically generated compressed streams, my CPU usage 
    drops to zero, while the crawlers still need to expend effort to 
    decompress the data.

    For example:

       # On startup.
       bomb = GzipObject()
       bomb.add("++?????++ Out of Cheese Error. Redo From Start.<br/>", reps=1000000)

       ...

       # For every request...
       generated_page = GzipObject()
       generated_page.add(some_content)
       generated_page.add(bomb)
       generated_page.add(some_more_content)
       send_to_client(generated_page.output())

    Some of this code takes inspiration from Python's gzip module.
    """

    def __init__(self, initialData = None, initialReps=1, timestamp=0):
        """
        Class constructor. If you pass a timestamp (time.time()) then
        it will be used in the gzip header. If you pass initialData
        and, optionally, initialReps, then the object's add() method
        will be called using these values.
        """
        self.length = 0
        self.compressed = []
        self.temp = b""
        self.crc = 0

        # Pre-create header and final chunk here. They're used 
        # in output()
        self.endchunk = zlib.compressobj(wbits=-15).flush(zlib.Z_FINISH)
        self.header = struct.pack("<BBBBLBB", 0x1f, 0x8b, 8, 0, int(timestamp), 2, 255)


        # We don't start a zlib compress object here. It gets
        # created in the add() method when needed.
        self.compressor = None

        # If data was pressed to the constructor, pass it
        # over the add() method.
        if initialData is not None:
            self.add(initialData, initialReps)

    def add(self, data, reps=1):
        """
        Add some data to the current object. If data is a string, 
        it is encoded as utf-8 and added. If it is a bytes array, 
        it is added unchanged. If it is another GzipChunk object
        then its compressed data is added directly.

        The optional "reps" argument allows you to add multiple 
        copies of the data.
        """
        if isinstance(data, GzipChunk):
            # A precompressed chunk.
            if len(data.compressed) != 1:
                # But it's the wrong size!
                raise Exception("Cannot add multi-chunk items")

            # To add pre-compressed data, we need to flush the
            # current compression object.
            if self.compressor is not None:
                # We currently have an open chunk. Flush it and discard the
                # compress object.
                self.compressed[-1] = self.compressed[-1] + self.compressor.flush(zlib.Z_FULL_FLUSH)
                self.compressor = None

            # If the added object has an open chunk, that needs to 
            # be flushed first so that we've got a consistent
            # compressed chunk to add.
            if data.compressor is not None:
                data.compressed[0] += data.compressor.flush(zlib.Z_FULL_FLUSH)
                data.compressor = None

            # Now add however many copies are required.
            for i in range(reps):
                self.length += data.length
                self.compressed.append(data.compressed[0])
                self.crc = ctypes_zlib.crc32_combine(self.crc, data.crc, data.length)
        else:
            # Not pre-compressed data. Hopefully a string or a bytes array.
            if isinstance(data, str):
                # String - encode it to bytes.
                data = data.encode("utf-8")

            if self.compressor is None:
                # We have no compressor running. Create one and
                # add an empty chunk to our chunk list.
                self.compressor = zlib.compressobj(wbits=-15)
                self.compressed.append(b'')

            # Calculate the CRC of the supplied data chunk.
            crc = zlib.crc32(data)

            # Add however many repetitions were requested.
            for i in range(reps):
                self.compressed[-1] = self.compressed[-1] + self.compressor.compress(data)
                self.crc = ctypes_zlib.crc32_combine(self.crc, crc, len(data))
            self.length += reps*len(data)

    def output(self):
        # This is a bit fiddly, probably for no good reason. When
        # we call output, we'd rather not completely prevent this
        # object from having more stuff added. So we just flush
        # the current chunk, then manually add a finish chunk from 
        # a brand new compressobj which we then discard.
        if self.compressor is not None:
            self.compressed[-1] += self.compressor.flush(zlib.Z_FULL_FLUSH)
            self.compressor = None

        # The data CRC and length.
        trailer = struct.pack("<LL", self.crc, self.length & 0xFFFFFFFF)

        # OK, join it all together. Header, our collection of compressed chunks,
        # the end chunk and the trailer. This should form a usable gzip data
        # stream.
        return self.header + b"".join(self.compressed) + self.endchunk + trailer

# Test harness.
if __name__ == "__main__":
    import sys
    import time
    import gzip

    # Make a zip bomb to insert into
    # our output.
    print("Creating bomb...", file=sys.stderr)
    start = time.time()
    precalc = GzipChunk(b"++?????++ Out of Cheese Error. Redo From Start.<br/>\n", 100000)
    end = time.time()
    print(f"Bomb compressed length is {len(precalc.output())}, created in {end-start:.3f}s", file=sys.stderr)
    print(f"Bomb uncompressed length is {precalc.length}", file=sys.stderr)
    
    # Make the object.
    gz = GzipChunk()

    # Add some dynamic stuff.
    gz.add(f"""{time.strftime("%Y-%m-%d %H:%M:%S")}\n""".encode("utf-8"))

    # Add the bomb.
    gz.add(precalc)

    # Add some more stuff.
    gz.add(b"That was the time")

    # Add the bomb again, cos why not?
    # This is, after all, the whole point - that we can add
    # zip bombs inline into other output.
    gz.add(precalc)

    # Add some more stuff.
    gz.add(b"That was the time that was")

    # Get the compressed data.
    output = gz.output()

    print(f"Chunks: {len(gz.compressed)}", file=sys.stderr)
    print(f"Output length: {len(output)}", file=sys.stderr)
    print(f"Decompressed length: {len(gzip.decompress(output))}", file=sys.stderr)
    sys.stdout.buffer.write(output)
