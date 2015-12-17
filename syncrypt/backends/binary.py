import logging
import time

import asyncio
import umsgpack
from getpass import getpass

from .base import StorageBackend, StorageBackendInvalidAuth
from syncrypt.utils import readline_from_stdin

logger = logging.getLogger(__name__)

class BinaryStorageConnection(object):
    def __init__(self, storage):
        self.storage = storage
        self.available = asyncio.Event()
        self.available.clear()
        self.connected = False
        self.connecting = False

    @asyncio.coroutine
    def connect(self):
        logger.debug('Connecting to server...')
        self.reader, self.writer = \
                yield from asyncio.open_connection(self.storage.host,
                                                   self.storage.port)

        # version string format: "Syncrypt x.y.z\r\n"
        version_info = yield from self.reader.readline()
        self.server_version = version_info.decode().strip().split(" ")[1]

        if self.storage.auth:
            self.writer.write('AUTH:{0}\r\n'
                    .format(self.storage.auth)
                    .encode(self.storage.vault.config.encoding))
            yield from self.writer.drain()

            line = yield from self.reader.readline()
            if line != b'SUCCESS\r\n':
                yield from self.disconnect()
                raise StorageBackendInvalidAuth(line)
        else:
            # we don't have auth token yet
            logger.debug('Log into server...')
            self.writer.write('LOGIN:{0}:{1}:{2}\r\n'
                    .format(self.storage.username, self.storage.password, 'vault-id')
                    .encode(self.storage.vault.config.encoding))
            yield from self.writer.drain()

            line = yield from self.reader.readline()

            login_response = line.decode(self.storage.vault.config.encoding).strip('\r\n').split(':')
            if login_response[0] == '' or login_response[0] == 'ERROR':
                yield from self.disconnect()
                raise StorageBackendInvalidAuth(line)
            self.storage.auth = login_response[0]

        self.connected = True
        self.connecting = False
        self.available.set()

    @asyncio.coroutine
    def disconnect(self):
        logger.debug('Disconnecting from server...')
        try:
            self.writer.write(b'DISCONNECT\r\n')
            yield from self.writer.drain()
        except:
            pass
        self.writer.close()
        self.connected = False
        self.connecting = False
        self.available.set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.available.set()

    @asyncio.coroutine
    def stat(self, bundle):
        logger.info('Stat %s', bundle)

        self.writer.write('STAT:{0.store_hash}\r\n'
                .format(bundle)
                .encode(self.storage.vault.config.encoding))
        yield from self.writer.drain()

        line = yield from self.reader.readline()
        try:
            byte_count = int(line)
        except ValueError as e:
            return None

        msg = yield from self.reader.read(byte_count)

        return umsgpack.loads(msg)

    @asyncio.coroutine
    def upload(self, bundle):

        logger.info('Uploading %s', bundle)

        assert bundle.uptodate

        # upload key and file
        self.writer.write('UPLOAD:{0.store_hash}:{0.key_size_crypt}:{0.file_size_crypt}:{0.crypt_hash}\r\n'
                .format(bundle)
                .encode(self.storage.vault.config.encoding))
        yield from self.writer.drain()

        line = yield from self.reader.readline()
        if line != b'WAITING\r\n':
            raise Exception(line)

        logger.info('Uploading key ({0} bytes) and content ({1} bytes)'\
                .format(bundle.key_size_crypt, bundle.file_size_crypt))

        bytes_written = 0
        with open(bundle.path_key, 'rb') as f:
            while f.tell() < bundle.key_size_crypt:
                buf = f.read(self.storage.buf_size)
                self.writer.write(buf)
                bytes_written += len(buf)
                yield from self.writer.drain()
        assert bytes_written == bundle.key_size_crypt

        bytes_written = 0
        with open(bundle.path_crypt, 'rb') as f:
            while f.tell() < bundle.file_size_crypt:
                buf = f.read(self.storage.buf_size)
                self.writer.write(buf)
                bytes_written += len(buf)
                yield from self.writer.drain()
        assert bytes_written == bundle.file_size_crypt

        line = yield from self.reader.readline()
        if line != b'SUCCESS\r\n':
            raise Exception(line)

    @asyncio.coroutine
    def download(self, bundle):

        logger.info('Downloading %s', bundle)

        # upload key and file
        self.writer.write('DOWNLOAD:{0.store_hash}\r\n'
                .format(bundle)
                .encode(self.storage.vault.config.encoding))
        yield from self.writer.drain()

        key_size = int((yield from self.reader.readline()).strip(b'\r\n'))
        file_size = int((yield from self.reader.readline()).strip(b'\r\n'))

        logger.info('Downloading key ({0} bytes) and content ({1} bytes)'\
                .format(key_size, file_size))

        with open(bundle.path_key, 'wb') as f:
            while key_size > 0:
                buf = yield from self.reader.read(min(self.storage.buf_size, key_size))
                f.write(buf)
                key_size -= len(buf)
            assert key_size == 0

        with open(bundle.path_crypt, 'wb') as f:
            while file_size > 0:
                buf = yield from self.reader.read(min(self.storage.buf_size, file_size))
                f.write(buf)
                file_size -= len(buf)
            assert file_size == 0, file_size

    @asyncio.coroutine
    def version(self):
        return self.server_version

    @asyncio.coroutine
    def wipe(self):
        self.writer.write('WIPE-VAULT\r\n'
                .encode(self.storage.vault.config.encoding))
        yield from self.writer.drain()

        line = yield from self.reader.readline()
        if line != b'SUCCESS\r\n':
            raise Exception(line)


class BinaryStorageManager(object):

    def __init__(self, backend, concurrency):
        self.backend = backend
        self.concurrency = concurrency
        self.slots = [BinaryStorageConnection(backend) for i in range(concurrency)]

    @asyncio.coroutine
    def acquire_connection(self):
        'return an available connection or block until one is free'
        # trigger at most one connection
        for conn in self.slots:
            if not conn.connected and not conn.connecting:
                conn.connecting = True
                yield from conn.connect()
                break
            if conn.connected and conn.available.is_set():
                break

        # wait until one slot is available
        done, running = yield from \
                asyncio.wait([conn.available.wait() for conn in self.slots],
                            return_when=asyncio.FIRST_COMPLETED)

        for f in running: f.cancel()

        # find this slot
        for conn in self.slots:
            if conn.connected and conn.available.is_set():
                conn.available.clear()
                return conn

        # if we haven't found one, try again
        return (yield from self.acquire_connection())

class BinaryStorageBackend(StorageBackend):

    def __init__(self, vault, auth=None, host='127.0.0.1', port=1337,
            concurrency=4, username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.auth = auth
        self.buf_size = 10 * 1024
        self.concurrency = int(concurrency)
        self.upload_sem = asyncio.Semaphore(value=self.concurrency)
        self.manager = BinaryStorageManager(self, self.concurrency)
        super(BinaryStorageBackend, self).__init__(vault)

    @asyncio.coroutine
    def init(self):
        self.username = None
        while not self.username:
            print('Email for {}: '.format(self.host), end='', flush=True)
            self.username = yield from readline_from_stdin()
        self.password = getpass()
        try:
            with (yield from self.manager.acquire_connection()) as conn:
                # after successful login, write back config
                self.vault.config.update('remote', {'auth': self.auth})
                self.vault.write_config()
                print('OK')
        except StorageBackendInvalidAuth:
            logger.error('Invalid auth')

    @asyncio.coroutine
    def open(self):
        with (yield from self.manager.acquire_connection()) as conn:
            version = yield from conn.version()
            logger.info('Logged in to server (version %s)', version)

    @asyncio.coroutine
    def stat(self, bundle):
        with (yield from self.manager.acquire_connection()) as conn:
            stat_info = yield from conn.stat(bundle)
            if not stat_info is None:
                if b'content_hash' in stat_info:
                    bundle.remote_crypt_hash = \
                            stat_info[b'content_hash'].decode()

    @asyncio.coroutine
    def upload(self, bundle):
        with (yield from self.manager.acquire_connection()) as conn:
            yield from conn.upload(bundle)

    @asyncio.coroutine
    def download(self, bundle):
        with (yield from self.manager.acquire_connection()) as conn:
            yield from conn.download(bundle)

    @asyncio.coroutine
    def wipe(self):
        with (yield from self.manager.acquire_connection()) as conn:
            yield from conn.wipe()

