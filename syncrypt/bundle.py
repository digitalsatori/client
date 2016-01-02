import hashlib
import logging
import os

import Crypto.Util.number
import rsa
from Crypto.Cipher import AES

import aiofiles
import asyncio

from .pipes import (Buffered, Decrypt, Encrypt, FileReader, FileWriter,
                    SnappyCompress, SnappyDecompress, Hash)

logger = logging.getLogger(__name__)

class Bundle(object):
    'A Bundle represents a file and some additional information'

    encrypt_semaphore = asyncio.Semaphore(value=8)
    decrypt_semaphore = asyncio.Semaphore(value=8)

    __slots__ = ('path', 'vault', 'file_size', 'file_size_crypt',
            'key_size_crypt', 'store_hash', 'crypt_hash',
            'remote_crypt_hash', 'uptodate', 'update_handle', 'key')

    def __init__(self, abspath, vault):
        self.vault = vault
        self.path = abspath
        self.uptodate = False
        self.remote_crypt_hash = None
        self.update_handle = None

        h = hashlib.new(self.vault.config.hash_algo)
        h.update(self.relpath.encode(self.vault.config.encoding))
        self.store_hash = h.hexdigest()

    @property
    def key_size(self):
        return self.vault.config.aes_key_len >> 3

    @property
    def remote_hash_differs(self):
        return self.remote_crypt_hash is None or \
                self.remote_crypt_hash != self.crypt_hash

    @asyncio.coroutine
    def load_key(self):
        key_file = yield from aiofiles.open(self.path_key, 'rb')
        try:
            encrypted_key = yield from key_file.read()
            self.key = self.vault.private_key.decrypt(encrypted_key)
            self.key_size_crypt = len(encrypted_key)
            assert len(self.key) == self.key_size
        finally:
            yield from key_file.close()

    @asyncio.coroutine
    def generate_key(self):
        aes_key = os.urandom(self.key_size)
        if not os.path.exists(os.path.dirname(self.path_key)):
            os.makedirs(os.path.dirname(self.path_key))
        with open(self.path_key, 'wb') as encrypted_key_file:
            (encrypted_key, ) = self.vault.public_key.encrypt(aes_key, 0)
            encrypted_key_file.write(encrypted_key)
            self.key_size_crypt = len(encrypted_key)
        self.key = aes_key
        assert len(self.key) == self.key_size

    def read_encrypted_stream(self):
        return FileReader(self.path) \
                >> SnappyCompress() \
                >> Buffered(self.vault.config.enc_buf_size) \
                >> Encrypt(self)

    @asyncio.coroutine
    def write_encrypted_stream(self, stream, assert_hash=None):
        hash_pipe = Hash(self)

        sink = stream \
                >> Buffered(self.vault.config.enc_buf_size) \
                >> hash_pipe \
                >> Decrypt(self) \
                >> SnappyDecompress() \
                >> FileWriter(self.path)

        try:
            yield from sink.consume()
            print (hash_pipe, assert_hash)
            if assert_hash and hash_pipe.hash != assert_hash:
                # TODO: restore original file and alert server
                raise Exception('hash mismatch!')
        finally:
            yield from sink.close()

    @asyncio.coroutine
    def update(self):
        'update encrypted hash (store in .vault)'

        yield from self.encrypt_semaphore.acquire()
        logger.info('Updating %s', self)

        try:
            yield from self.load_key()
        except:
            yield from self.generate_key()

        hashing_reader = self.read_encrypted_stream() >> Hash(self)
        try:
            yield from hashing_reader.consume()
        finally:
            yield from hashing_reader.close()

        self.crypt_hash = hashing_reader.hash
        self.file_size_crypt = hashing_reader.size
        self.uptodate = True
        self.encrypt_semaphore.release()

    def update_and_upload(self):
        backend = self.vault.backend
        def x(bundle):
            yield from bundle.update()
            yield from backend.stat(bundle)
            if bundle.remote_hash_differs:
                yield from backend.upload(bundle)
        asyncio.ensure_future(x(self))

    def schedule_update(self):
        if self.update_handle:
            self.update_handle.cancel()
        loop = asyncio.get_event_loop()
        self.update_handle = loop.call_later(1.0, self.update_and_upload)

    def __str__(self):
        return "<Bundle: {0.relpath}>".format(self)

    @property
    def relpath(self):
        return os.path.relpath(self.path, self.vault.folder)

    @property
    def path_key(self):
        return os.path.join(self.vault.keys_path, \
                self.store_hash[:2], self.store_hash)
