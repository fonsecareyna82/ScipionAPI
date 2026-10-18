"""Protocol output thumbnails served from the database and a signed disk cache.

catalog: which outputs a project has and the signature of each one, read from
the database without loading the project. store: where a thumbnail of a given
signature lives on disk. scheduler: renders the missing ones in worker
processes, several at a time.
"""
