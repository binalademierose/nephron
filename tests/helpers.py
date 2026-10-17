"""
helpers.py - shared setup for the tests that use the whole web app.

Each test gets its own app with an in-memory user store, so no test needs MySQL and no test can affect another.
"""
import os
import re
import sys
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["FLASK_DEBUG"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

PASSWORD = "a-long-enough-phrase"
NEW_PASSWORD = "a-brand-new-phrase-2026"


class AppTestCase(unittest.TestCase):
    debug = False          # a test class sets this to True to also get the /design previews

    model = None           # True = a READY stand-in model; "explainable" = one that can also explain a single result; None = no model
    stage2_model = None     # same idea, for the Enhanced Screening (Stage 2) model

    def setUp(self):
        self.store = MemoryUserStore()
        if self.model == "explainable" or self.stage2_model == "explainable":
            import model_fixtures
            patcher = model_fixtures.fake_xgboost()
            patcher.__enter__()
            self.addCleanup(patcher.__exit__, None, None, None)
        self.app = create_app({"DEBUG": True} if self.debug else None, user_store=self.store,
                              model_service=ready_model_service(explainable=self.model == "explainable") if self.model else None,
                              model_service_stage2=ready_stage2_model_service(explainable=self.stage2_model == "explainable") if self.stage2_model else None)
        self.client = self.app.test_client()

    # ---- talking to the app the way a browser does ----
    def csrf(self, client=None, path="/login"):
        """Open a page that has a form and read the secret token out of it, like a browser would send it back."""
        html = (client or self.client).get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, path, data=None, client=None, token_from="/login", token=True, **kwargs):
        """POST a form. token=True adds the right CSRF token; token=None sends none; a string sends that string."""
        client = client or self.client
        data = dict(data or {})
        if token is True:
            data["csrf_token"] = self.csrf(client, token_from)
        elif token:
            data["csrf_token"] = token
        return client.post(path, data=data, **kwargs)

    def register(self, client=None, **changes):
        form = {"role": "general", "full_name": "Ana Reyes", "email": "ana@example.com", "password": PASSWORD,
               "confirm_password": PASSWORD, "username": f"user_{uuid.uuid4().hex[:12]}", "date_of_birth": "1978-05-14",
               "address": "", "avatar": "avatar-1", "country": "Other"}
        # 1978 and "Other" match the default screening answers (Age 48, Country Other), which are now fixed by the
        # account's own birthday and country (services/fixed_answers.py).
        form.update(changes)
        if "confirm_password" not in changes and "password" in changes:
            form["confirm_password"] = changes["password"]        # a test changing the password still confirms it correctly
        return self.post("/register", form, client, token_from="/register")

    def login(self, client=None, email="ana@example.com", password=PASSWORD, **extra):
        return self.post("/login", {"email": email, "password": password, **extra}, client)

    def add_assessment(self, email="ana@example.com", **changes):
        """Save a made-up test result for an existing account, exactly as the screening phase will save a real one."""
        from datetime import datetime
        from services import assessments
        values = {"assessment_type": "preliminary", "probability": 0.31, "classification": "high", "threshold_used": 0.21,
                  "model_version": "test-model", "assessed_at": datetime(2026, 9, 18, 4, 0, 0)}
        inputs = changes.pop("inputs", None)                     # the answers behind the result, if the test needs them
        values.update(changes)
        user = self.store.find_by_email(email)
        return assessments.record_assessment(self.app.extensions["assessment_store"], user["user_id"], values, inputs)

    def new_browser(self):
        return self.app.test_client()

    def signed_in(self, **changes):
        """A browser that has just registered (and is therefore signed in)."""
        browser = self.new_browser()
        self.register(browser, **changes)
        return browser

    def professional_details(self, **changes):
        details = {"role": "professional", "profession_title": "Nephrologist", "email": "dr.cruz@example.com", "full_name": "Dr. Luis Cruz"}
        details.update(changes)
        return details

    def new_username(self):
        return f"user_{uuid.uuid4().hex[:12]}"

    def text(self, response):
        return response.get_data(as_text=True)


# ---- a stand-in screening model, shared by the tests that need a READY model (see tests/model_fixtures.py) ----
_STAND_IN = {}


def ready_model_service(explainable=False):
    """
    A model service loaded from a stand-in model (NOT Nephron's model). Built once per test run, then reused.
    explainable=True gives the additive stand-in that can explain a single result (it needs the fake xgboost that
    AppTestCase installs, so use it through a test class with model = "explainable").
    """
    import atexit
    import shutil
    import tempfile
    import model_fixtures
    from services import screening_contract
    from services.model_service import ModelService

    key = "explainable" if explainable else "plain"
    if key not in _STAND_IN:
        catalog = screening_contract.load_catalog()
        folder = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, folder, True)
        model_fixtures.build_stand_in(folder, catalog, estimator="additive" if explainable else "gradient")
        service = ModelService(folder, catalog)
        if explainable:
            with model_fixtures.fake_xgboost():
                assert service.load(), service.reason
        else:
            assert service.load(), service.reason
        _STAND_IN[key] = service
    return _STAND_IN[key]


# ---- a stand-in Stage 2 (Enhanced Screening) model, shared by the tests that need a READY one ----
_STAGE2_STAND_IN = {}


def ready_stage2_model_service(explainable=False):
    """Same idea as ready_model_service(), for services/model_service_stage2.py."""
    import atexit
    import shutil
    import tempfile
    import model_fixtures
    from services import lab_contract
    from services.model_service_stage2 import Stage2ModelService

    key = "explainable" if explainable else "plain"
    if key not in _STAGE2_STAND_IN:
        catalog = lab_contract.load_lab_catalog()
        folder = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, folder, True)
        model_fixtures.build_stage2_stand_in(folder, catalog)
        service = Stage2ModelService(folder, catalog)
        if explainable:
            with model_fixtures.fake_xgboost():
                assert service.load(), service.reason
        else:
            assert service.load(), service.reason
        _STAGE2_STAND_IN[key] = service
    return _STAGE2_STAND_IN[key]
