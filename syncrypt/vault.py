import logging
from fnmatch import fnmatch
import os
import os.path
import sys
from pprint import pprint

from Crypto.PublicKey import RSA

from .bundle import Bundle
from .config import VaultConfig

logger = logging.getLogger(__name__)

class Vault(object):
    def __init__(self, folder):
        self.folder = folder
        self._bundle_cache = {}
        assert os.path.exists(folder)

        self.config = VaultConfig()
        if os.path.exists(self.config_path):
            logger.info('Using config file: %s', self.config_path)
            self.config.read(self.config_path)
        else:
            self.write_config(self.config_path)

        id_rsa_path = os.path.join(folder, '.vault', 'id_rsa')
        id_rsa_pub_path = os.path.join(folder, '.vault', 'id_rsa.pub')
        if not os.path.exists(id_rsa_path) or not os.path.exists(id_rsa_pub_path):
            self.init_keys(id_rsa_path, id_rsa_pub_path)
        else:
            with open(id_rsa_pub_path, 'rb') as id_rsa_pub:
                self.public_key = RSA.importKey(id_rsa_pub.read())
            with open(id_rsa_path, 'rb') as id_rsa:
                self.private_key = RSA.importKey(id_rsa.read())

        Backend = self.config.backend_cls
        kwargs = self.config.backend_kwargs
        # TODO make property?
        self.backend = Backend(self, **kwargs)

    @property
    def crypt_path(self):
        return os.path.join(self.folder, '.vault', 'data')

    @property
    def keys_path(self):
        return os.path.join(self.folder, '.vault', 'keys')

    @property
    def config_path(self):
        return os.path.join(self.folder, '.vault', 'config')

    def write_config(self, config_path=None):
        if config_path is None:
            config_path = self.config_path
        if not os.path.exists(os.path.dirname(config_path)):
            os.makedirs(os.path.dirname(config_path))
        logger.info('Writing config to %s', config_path)
        self.config.write(config_path)

    def init_keys(self, id_rsa_path, id_rsa_pub_path):
        if not os.path.exists(os.path.dirname(id_rsa_path)):
            os.makedirs(os.path.dirname(id_rsa_path))
        logger.info('Generating RSA key pair...')
        keys = RSA.generate(self.config.rsa_key_len)
        with open(id_rsa_pub_path, 'wb') as id_rsa_pub:
            id_rsa_pub.write(keys.publickey().exportKey())
        with open(id_rsa_path, 'wb') as id_rsa:
            id_rsa.write(keys.exportKey())
        self.private_key = keys
        self.public_key = keys.publickey()

    def walk(self, subfolder=None):
        'a generator of all bundles in this vault'
        folder = self.folder
        if subfolder:
            folder = os.path.join(folder, subfolder)
        for file in os.listdir(folder):
            if any(fnmatch(file, ig) for ig in self.config.ignore_patterns):
                continue
            abspath = os.path.join(folder, file)
            relpath = os.path.relpath(abspath, self.folder)
            if os.path.isdir(abspath):
                yield from self.walk(subfolder=relpath)
            else:
                yield self.bundle_for(relpath)

    def bundle_for(self, relpath):
        # check if path should be ignored
        for filepart in relpath.split('/'):
            if any(fnmatch(filepart, ig) for ig in self.config.ignore_patterns):
                return None

        if os.path.isdir(os.path.join(self.folder, relpath)):
            return None

        if not relpath in self._bundle_cache:
            self._bundle_cache[relpath] =\
                    Bundle(os.path.join(self.folder, relpath), vault=self)

        return self._bundle_cache[relpath]
