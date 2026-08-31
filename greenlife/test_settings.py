import os

os.environ.setdefault('DEBUG','1')
os.environ.setdefault('SECRET_KEY','greenlife-tests-only-secret-key')

from .settings import *

SECRET_KEY='greenlife-tests-only-secret-key'
DEBUG=True
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR/'test.sqlite3'}}
PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
