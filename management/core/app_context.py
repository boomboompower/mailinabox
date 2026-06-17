# Shared singletons. Both daemon.py and every view module import these from
# here (never from daemon.py itself) so there's no circular import between
# the app assembly point and the route modules it registers.

from core import utils
import auth.auth as auth

env = utils.load_environment()
auth_service = auth.AuthService()
