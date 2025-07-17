# What is it?

This is another component in my continuing fight against abusive web
crawlers. A recent blog post suggested that feeding zip bombs to 
crawlers was an effective approach to discouraging them.

I have by doubts about feeding a "traditional" zip bomb to a crawler.
The "traditional" approach is to have a file that expands to something
extremely large (many GBytes of data). It seems to me that any large 
scale crawler would have protections in place against this sort of 
thing, if only because the Internet is full of large files.

However, feeding them something quite large, as part of a generated page,
seems like it could be worthwhile. If the crawler has to decode and
parse a few tens of MBytes of highly compressed data, embedded within 
an otherwise innocuous page, that would increase their workload. The 
highly compressed data won't cost me much, in terms of bandwidth, but
it will cost them in terms of CPU usage.

For example, 30 MBytes of "Out of cheese error\n" compresses to around
76 KBytes. It costs me 76 KBytes of bandwidth to feed it to them, but 
an LLM crawler would need to ingest all 30 MBytes.

So here's the problem. If I want to insert those messages into a compressed
page, I need to compress them. If I'm generating pages on demand, that
compression work involves a lot of CPU usage at my end. More, actually, than
the work needed to decompress the data at the other end.

I got to thinking about gzip's "--rsyncable" flag. This makes gzipped files
more amenable to transfer via rsync by, somehow, resetting the compressed
stream every now and then. I won't go into detail what that's for, but if
the gzip file format can reset the compression stream, that implies that 
we could insert a pre-compressed chunk of data: compress whatever comes 
before our zip bomb, reset the stream, insert the pre-compressed chunk,
reset again and continue with whatever comes after the zip bomb.

Digging into the Python "gzip" module, and the underlying zlib library
showed this was definitely likely to work. And the result is gzipchunk.

Basically, you create a GzipChunk object and call its "add()" method
with a "data" argument (possibly with a repeat count). If the "data" 
argument is a bytes object or a string, it gets added to the compression
stream, compressing on the fly. If it's another "GzipChunk" object, then
the current object's stream gets a "reset" added, then the add()
object's compressed data gets added.

So you could do something like:

     # On startup, create a 30 MByte pre-compressed zip bomb
     zipbomb = GzipChunk("Out of cheese\n", 1600000)
     
     # For each request
     response = GzipChunk()
     response.add(some_html)
     response.add(zipbomb)
     response.add(some_more_html)
     transmit_compressed_page(response.output())

```transmit_compressed_page``` will be handed a valid gzipped stream, with 
30MBytes of zip bomb, but that 30MBytes will only have to be compressed
once on startup.

I hope this makes sense. It seems like a worthwhile thing to do,
and my deployment of [spigot](https://github.com/gw1urf/spigot/) on
my [personal website](https://www.ty-penguin.org.uk/~auj/spigot/)
is using it. With around 2% probability, generated pages get around
12.5MByte chunk of garbage added (which is pre-compressed to around
36KBytes). I also send the zip bomb whenever spigot is under too 
much load, instead of generating Markov chain output. At present,
Spigot is supplying around 4 Million pages per day. With the zip
bomb inserted, that's clocking in at around 15 TBytes per day. Actual
data supplied is under 70 GBytes per day.

# Portability

I should note that, because of the incremental way in which gzipped
streams is built by the library, gzipchunk needs to be able to access
zlib's "crc32_combine" function. This isn't exposed by the Python
library, so gzipchunk currently uses the "ctypes" module to load the
zlib shared library and call the function. This has been tested on
Debian Linux only. I suspect it will work on other Linux systems, 
but it will almost certainly need changes to get it working on Windows
and macOS.
