import configparser

class VaultConfig(object):
    rsa_key_len = 1024
    encoding = 'utf-8'

    def __init__(self):
        self._config = configparser.ConfigParser()
        # set defaults
        self._config['vault'] = {
                'ignore': '^.',
            }
        self._config['remote'] = {
                'type': 'binary',
            }

    def read(self, config_file):
        self._config.read(config_file)

    def write(self, config_file):
        with open(config_file, 'w') as f:
            self._config.write(f)

    @property
    def backend_cls(self):
        if self._config['remote']['type'] == 'local':
            from .backends import LocalStorageBackend
            return LocalStorageBackend
        elif self._config['remote']['type'] == 'binary':
            from .backends import BinaryStorageBackend
            return BinaryStorageBackend
        else:
            raise Exception(self._config['remote']['type'])

    @property
    def backend_kwargs(self):
        kwargs = dict(self._config['remote']) # copy dict
        kwargs.pop('type')
        return kwargs

