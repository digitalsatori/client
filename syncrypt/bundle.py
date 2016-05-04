import hashlib
import logging
import os

import Crypto.Util.number
from Crypto.Cipher import AES

import aiofiles
import asyncio
import umsgpack

from .pipes import (Buffered, DecryptAES, DecryptRSA_PKCS1_OAEP, EncryptAES,
                    EncryptRSA_PKCS1_OAEP, FileReader, FileWriter, Hash, Once,
                    PadAES, UnpadAES, SnappyCompress, SnappyDecompress, Count)

logger = logging.getLogger(__name__)

class Bundle(object):
    'A Bundle represents a file and some additional information'

    encrypt_semaphore = asyncio.Semaphore(value=8)
    decrypt_semaphore = asyncio.Semaphore(value=8)

    __slots__ = ('path', 'vault', 'file_size', 'file_size_crypt',
            'key_size_crypt', 'store_hash', 'crypt_hash',
            'remote_crypt_hash', 'uptodate', 'update_handle', 'key',
            'bytes_written')

    def __init__(self, abspath, vault, store_hash=None):
        self.vault = vault
        self.path = abspath
        self.uptodate = False
        self.remote_crypt_hash = None
        self.update_handle = None
        self.key = None
        self.bytes_written = 0

        if self.path is not None:
            h = hashlib.new(self.vault.config.hash_algo)
            h.update(self.relpath.encode(self.vault.config.encoding))
            self.store_hash = h.hexdigest()
        if store_hash is not None:
            self.store_hash = store_hash

    @property
    def bundle_size(self):
        return len(self.serialized_bundle)

    @property
    def serialized_bundle(self):
        return umsgpack.dumps(self.bundle)

    @property
    def bundle(self):
        return {
            'filename': os.path.relpath(self.path, self.vault.folder),
            'key': self.key,
            'hash': b'\0' * 32,
            'key_size': self.key_size
        }

    @property
    def key_size(self):
        return self.vault.config.aes_key_len >> 3

    @property
    def remote_hash_differs(self):
        return self.remote_crypt_hash is None or \
                self.remote_crypt_hash != self.crypt_hash

    @asyncio.coroutine
    def load_key(self):
        key_file = yield from aiofiles.open(self.path_fileinfo, 'rb')
        try:
            encrypted_key = yield from key_file.read()
            fileinfo = umsgpack.loads(encrypted_key)
            self.key = fileinfo[b'key']
            if self.path is None:
                self.path = os.path.join(self.vault.folder, fileinfo[b'filename'].decode())
            else:
                assert self.path == os.path.join(self.vault.folder, fileinfo[b'filename'].decode())
            self.key_size_crypt = len(encrypted_key)
            assert len(self.key) == self.key_size
        finally:
            yield from key_file.close()

    @asyncio.coroutine
    def generate_key(self):
        self.key = os.urandom(self.key_size)
        if not os.path.exists(os.path.dirname(self.path_fileinfo)):
            os.makedirs(os.path.dirname(self.path_fileinfo))
        assert len(self.key) == self.key_size

        sink = Once(self.serialized_bundle) >> FileWriter(self.path_fileinfo)
        yield from sink.consume()

    def encrypted_fileinfo_reader(self):
        return Once(self.serialized_bundle) \
                >> SnappyCompress() \
                >> EncryptRSA_PKCS1_OAEP(self.vault.identity.public_key)

    def read_encrypted_stream(self):
        assert not self.key is None
        return FileReader(self.path) \
                >> SnappyCompress() \
                >> Buffered(self.vault.config.enc_buf_size) \
                >> PadAES() \
                >> EncryptAES(self.key)

    @asyncio.coroutine
    def write_encrypted_stream(self, stream, assert_hash=None):
        hash_pipe = Hash(self.vault.config.hash_algo)

        if self.key is None:
            yield from self.load_key()

        sink = stream \
                >> Buffered(self.vault.config.enc_buf_size, self.vault.config.block_size) \
                >> DecryptAES(self.key) \
                >> UnpadAES() \
                >> SnappyDecompress() \
                >> hash_pipe \
                >> FileWriter(self.path, create_dirs=True, create_backup=True, store_temporary=True)

        yield from sink.consume()

        hash_obj = hash_pipe.hash_obj
        hash_obj.update(self.key)
        received_hash = hash_obj.hexdigest()

        passed = not assert_hash or received_hash == assert_hash

        if not passed:
            logger.error('hash mismatch: {} != {}'.format(assert_hash, received_hash))

        yield from sink.finalize()

        return passed

    @asyncio.coroutine
    def write_encrypted_fileinfo(self, stream):
        logger.debug("Updating fileinfo on disk")
        sink = stream \
                >> DecryptRSA_PKCS1_OAEP(self.vault.identity.private_key) \
                >> SnappyDecompress() \
                >> FileWriter(self.path_fileinfo, create_dirs=True)

        yield from sink.consume()
        assert os.path.exists(self.path_fileinfo)

    @asyncio.coroutine
    def update(self):
        'update encrypted hash (store in .vault)'

        yield from self.vault.semaphores['update'].acquire(self)
        yield from self.encrypt_semaphore.acquire()
        #logger.info('Updating %s', self)

        try:
            yield from self.load_key()
        except FileNotFoundError:
            yield from self.generate_key()

        assert self.path is not None

        if os.path.exists(self.path):

            # This will calculate the hash of the file contents
            # As such it will never be sent to the server (see below)
            # TODO: check impact of SnappyCompress and PadAES pipes on
            #       performance. Both are only needed for knowing the
            #       file size in upload. If they have a huge impact on
            #       performance, try to change the protocol so that the
            #       stream size does not need to be known inb4 by the
            #       client source.
            hashing_reader = FileReader(self.path) \
                        >> Hash(self.vault.config.hash_algo)

            counting_reader = hashing_reader \
                        >> SnappyCompress() \
                        >> Buffered(self.vault.config.enc_buf_size) \
                        >> PadAES() \
                        >> Count()
            yield from counting_reader.consume()

            # We add the AES key to the hash so that the hash stays
            # constant when the files is not changed, but the original
            # hash is also not revealed to the server
            assert len(self.key) == self.key_size
            hash_obj = hashing_reader.hash_obj
            hash_obj.update(self.key)

            self.crypt_hash = hash_obj.hexdigest()

            # Add one time the symmetric block_size to the encrypted file size.
            # This is the length of the IV.
            self.file_size_crypt = counting_reader.count + \
                    self.vault.config.block_size
            self.uptodate = True
        else:
            self.crypt_hash = None
            self.file_size_crypt = None
            self.uptodate = True

        self.encrypt_semaphore.release()
        yield from self.vault.semaphores['update'].release(self)

    def update_and_upload(self):
        backend = self.vault.backend
        def _update(bundle):
            logger.debug('Scheduled update is executing for %s', bundle)
            yield from bundle.update()
            yield from backend.stat(bundle)
            if bundle.remote_hash_differs:
                yield from backend.upload(bundle)
        asyncio.ensure_future(_update(self))

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
    def path_fileinfo(self):
        return os.path.join(self.vault.fileinfo_path, \
                self.store_hash[:2], self.store_hash[2:])
