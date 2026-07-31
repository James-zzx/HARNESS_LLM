import getpass
import json

import click
import keyring


class KeyringBackend:
    def set_password(self, service, key, value):
        keyring.set_password(service, key, value)

    def get_password(self, service, key):
        return keyring.get_password(service, key)

    def delete_password(self, service, key):
        try:
            keyring.delete_password(service, key)
        except keyring.errors.PasswordDeleteError:
            pass


class MemoryBackend:
    def __init__(self):
        self._data = {}

    def set_password(self, service, key, value):
        self._data.setdefault(service, {})[key] = value

    def get_password(self, service, key):
        return self._data.get(service, {}).get(key)

    def delete_password(self, service, key):
        self._data.get(service, {}).pop(key, None)


class CredentialStore:
    _INDEX_KEY = "__keys__"

    def __init__(self, backend=None):
        self._backend = backend if backend is not None else KeyringBackend()

    def set_key(self, service, key, value):
        self._backend.set_password(service, key, value)
        keys = self.list_keys(service)
        if key not in keys:
            keys.append(key)
            self._backend.set_password(service, self._INDEX_KEY, json.dumps(keys))

    def get_key(self, service, key):
        if key == self._INDEX_KEY:
            return None
        return self._backend.get_password(service, key)

    def delete_key(self, service, key):
        self._backend.delete_password(service, key)
        keys = self.list_keys(service)
        if key in keys:
            keys.remove(key)
            if keys:
                self._backend.set_password(service, self._INDEX_KEY, json.dumps(keys))
            else:
                self._backend.delete_password(service, self._INDEX_KEY)

    def list_keys(self, service):
        raw = self._backend.get_password(service, self._INDEX_KEY)
        if not raw:
            return []
        return json.loads(raw)


def prompt_for_key(key_name):
    return getpass.getpass(f"Enter value for '{key_name}': ")


def build_cred_cli(store=None):
    @click.group(name="cred")
    def cred_group():
        """Manage credentials stored securely in the OS keyring."""

    @cred_group.command("set")
    @click.argument("service")
    @click.argument("key")
    def set_command(service, key):
        current = store or CredentialStore()
        value = prompt_for_key(key)
        current.set_key(service, key, value)
        click.echo(f"Stored credential '{service}/{key}'.")

    @cred_group.command("get")
    @click.argument("service")
    @click.argument("key")
    def get_command(service, key):
        current = store or CredentialStore()
        value = current.get_key(service, key)
        if value is None:
            click.echo(f"No credential '{service}/{key}' found.", err=True)
            raise click.exceptions.Exit(1)
        click.echo(value)

    @cred_group.command("delete")
    @click.argument("service")
    @click.argument("key")
    def delete_command(service, key):
        current = store or CredentialStore()
        current.delete_key(service, key)
        click.echo(f"Deleted credential '{service}/{key}'.")

    @cred_group.command("list")
    @click.argument("service")
    def list_command(service):
        current = store or CredentialStore()
        for key in current.list_keys(service):
            click.echo(key)

    return cred_group
