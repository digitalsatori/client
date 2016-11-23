import json
import os
import os.path
import shutil
import time
import unittest
from glob import glob

import aiohttp
import asyncio
import asynctest
import hypothesis.strategies as st
from syncrypt.app import SyncryptApp
from syncrypt.backends import BinaryStorageBackend, LocalStorageBackend
from syncrypt.config import AppConfig
from syncrypt.models import Vault
from tests.base import VaultTestCase

from syncrypt.api import APIClient
import syncrypt

class APITests(VaultTestCase):
    folder = 'tests/testbinaryvault/'
    login_data = {
        'email': 'test@syncrypt.space',
        'password': 'test!password'
    }

    def test_api_login(self):
        'try to get a list of files via API'
        app = self.app
        client = APIClient(self.app_config)
        yield from app.start()
        try:
            r = yield from client.login(**self.login_data)
            yield from r.release()
            self.assertEqual(r.status, 200)

            r = yield from client.get('/v1/auth/check/')
            c = yield from r.json()
            yield from r.release()
            self.assertEqual(r.status, 200)
            self.assertEqual(c['connected'], True)

            r = yield from client.logout()
            c = yield from r.json()
            self.assertEqual(r.status, 200)
            yield from r.release()

            r = yield from client.get('/v1/auth/check/')
            c = yield from r.json()
            self.assertEqual(r.status, 200)
            yield from r.release()
            self.assertEqual(c['connected'], False)

        finally:
            yield from app.stop()

    def test_api_bundle(self):
        'try to get a list of files via API'
        app = self.app
        app.add_vault(self.vault)
        client = APIClient(self.app_config)

        yield from app.init(self.vault)
        yield from app.start()

        try:
            r = yield from client.get('/v1/vault/')
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            self.assertEqual(len(c), 1) # only one vault
            yield from r.release()

            vault_uri = c[0]['resource_uri']

            r = yield from client.get(vault_uri)
            yield from r.release()

            # get a list of bundles
            bundle_list_uri = '%sbundle/' % vault_uri

            r = yield from client.get(bundle_list_uri)
            c = yield from r.json()
            self.assertEqual(len(c), 8)
            #from pprint import pprint; pprint(c)
            yield from r.release()
        finally:
            yield from app.stop()

    def test_api_add_user(self):
        app = self.app
        client = APIClient(self.app_config)

        yield from app.init(self.vault)
        yield from app.start()

        clone_folder = os.path.join(self.working_dir, 'cloned')
        if os.path.exists(clone_folder):
            shutil.rmtree(clone_folder)

        try:
            r = yield from client.login(**self.login_data)
            yield from r.release()
            self.assertEqual(r.status, 200)

            yield from asyncio.sleep(0.1)

            r = yield from client.get('/v1/vault/')
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            self.assertEqual(len(c), 0) # no vault
            yield from r.release()

            r = yield from client.post('/v1/vault/',
                    data=json.dumps({ 'folder': self.vault.folder }))
            c = yield from r.json()
            self.assertGreater(len(c['resource_uri']), 5)
            yield from r.release()

            teh_vault = c['resource_uri']

            r = yield from client.get('/v1/vault/')
            c = yield from r.json()
            self.assertEqual(len(c), 1) # one vault
            yield from r.release()

            r = yield from client.get(teh_vault + 'users/')
            c = yield from r.json()

            self.assertEqual(len(c), 1) # one user
            yield from r.release()
            me = c[0]

            # add_user will make sure that the email is added as a user to the vault.
            # it will then return all the keys.
            # For testing purpose, we will add ourselves again

            r = yield from client.get('/v1/user/' + me['email'] + '/keys/')
            c = yield from r.json()
            self.assertGreater(len(c), 0) # at least one key
            yield from r.release()
            fingerprint = c[0]['fingerprint']

            r = yield from client.post(teh_vault + 'users/',
                data=json.dumps({
                    'email': me['email'],
                    'fingerprints': [fingerprint]
                }))
            c = yield from r.json()
            yield from r.release()

            r = yield from client.get(teh_vault + 'users/' + me['email'] + '/keys/')
            c = yield from r.json()
            self.assertGreater(len(c), 0) # at least one key
            yield from r.release()

            r = yield from client.delete(teh_vault)
            self.assertEqual(r.status, 200)
            yield from r.release()

            r = yield from client.get('/v1/vault/')
            c = yield from r.json()
            self.assertEqual(len(c), 0) # no vault
            yield from r.release()

            # now lets try to clone the vault

            post_data = json.dumps({
                'folder': clone_folder,
                'id': self.vault.config.id
            })

            r = yield from client.post('/v1/vault/', data=post_data)
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            yield from r.release()

            r = yield from client.get('/v1/vault/')
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            yield from r.release()
            self.assertEqual(len(c), 1)

            self.assertEqual(c[0]['metadata'].get('name'), 'testvault')

            # TODO actually we need to wait for backend future here
            yield from asyncio.sleep(1.0)

        finally:
            yield from app.stop()

    def test_api_push(self):
        app = self.app
        client = APIClient(self.app_config)

        app.add_vault(self.vault)

        yield from app.init(self.vault)
        yield from app.start()

        try:

            r = yield from client.get('/v1/vault/')
            c = yield from r.json()
            self.assertEqual(len(c), 1) # only one vault
            yield from r.release()

            r = yield from client.get('/v1/stats')
            c = yield from r.json()
            self.assertEqual(c['stats']['downloads'], 0)
            self.assertEqual(c['stats']['uploads'], 8)
            self.assertEqual(c['stats']['stats'], 8)
            yield from r.release()

            yield from app.push()

            r = yield from client.get('/v1/stats')
            c = yield from r.json()
            self.assertEqual(c['stats']['downloads'], 0)
            self.assertEqual(c['stats']['uploads'], 8)
            self.assertEqual(c['stats']['stats'], 16)
            yield from r.release()

            r = yield from client.get('/v1/config')
            c = yield from r.json()
            self.assertIn('api', c.keys())
            yield from r.release()

            r = yield from client.get('/v1/vault/')
            c = yield from r.json()
            self.assertEqual(len(c), 1) # still only one vault
            yield from r.release()

            self.assertFalse(c[0]['modification_date'] is None)

        finally:
            yield from app.stop()

    def test_api_metadata(self):
        app = self.app
        client = APIClient(self.app_config)

        app.add_vault(self.vault)

        yield from app.init(self.vault)
        yield from app.start()

        try:

            r = yield from client.get('/v1/vault/')
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            yield from r.release()

            self.assertEqual(len(c), 1) # only one vault

            vault_uri = c[0]['resource_uri']

            r = yield from client.get(vault_uri)
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            yield from r.release()

            self.assertEqual(c['metadata'].get('name'), 'testvault')

            patch_data = json.dumps({
                'metadata': dict(c['metadata'], name='newname')
            })
            r = yield from client.put(vault_uri, data=patch_data)
            self.assertEqual(r.status, 200)
            yield from r.release()

            r = yield from client.get(vault_uri)
            self.assertEqual(r.status, 200)
            c = yield from r.json()
            yield from r.release()

            self.assertEqual(c['metadata'].get('name'), 'newname')

        finally:
            yield from app.stop()

    def test_api_feedback(self):
        'try to send some feedback over API'
        app = self.app
        client = APIClient(self.app_config)
        yield from app.start()
        try:
            r = yield from client.login(**self.login_data)
            yield from r.release()
            self.assertEqual(r.status, 200)

            r = yield from client.post('/v1/feedback/', data=json.dumps({
                'feedback_text': 'Hey there fellas!'
            }))
            c = yield from r.json()
            yield from r.release()
            self.assertEqual(r.status, 200)

        finally:
            yield from app.stop()

    def test_api_shutdown(self):
        app = self.app
        client = APIClient(self.app_config)
        yield from app.start()
        try:
            r = yield from client.get('/v1/version/', params={'check_for_update': 0})
            c = yield from r.json()
            yield from r.release()
            self.assertEqual(r.status, 200)

            self.assertEqual(c['installed_version'], syncrypt.__version__)
            self.assertNotIn('update_available', c)

            r = yield from client.get('/v1/shutdown/')
            c = yield from r.json()
            yield from r.release()
            self.assertEqual(r.status, 200)

        finally:
            yield from app.wait_for_shutdown()

