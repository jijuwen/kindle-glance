"""Check the pinned CLI protocol with an empty, disposable credential store."""
from pathlib import Path
import tempfile
from rpc import CodexRPC, RpcError

with tempfile.TemporaryDirectory() as directory:
    client = CodexRPC(Path(directory))
    try:
        result = client.call('account/read', {'refreshToken': False})
        assert result.get('account') is None, 'Disposable CLI unexpectedly has an account'
        try:
            client.call('account/rateLimits/read')
        except RpcError as error:
            assert 'auth' in str(error).lower() or 'account' in str(error).lower(), str(error)
        else:
            raise AssertionError('Unauthenticated rate limits should require login')
        print('PASS: initialize, account/read and unauthenticated rate-limit protocol; no model or login call')
    finally:
        client.close()
