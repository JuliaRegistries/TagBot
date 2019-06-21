import os
import sys

sys.path.insert(0, "../tagbot")
os.environ["GITHUB_APP_ID"] = "100"
os.environ["GITHUB_APP_NAME"] = "julia-tagbot"
os.environ["GITHUB_WEBHOOK_SECRET"] = "abcdef"
os.environ["GIT_TAGGER_EMAIL"] = "julia.tagbot@gmail.com"
os.environ["GIT_TAGGER_NAME"] = "Julia TagBo"
os.environ["LAMBDA_FUNCTION_PREFIX"] = "TagBot-test-"
os.environ["REGISTRATOR_USERNAME"] = "JuliaRegistrator"
