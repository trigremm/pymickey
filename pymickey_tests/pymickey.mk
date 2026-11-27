# pymickey.mk - run the sample suite in pymickey_tests/ (env_file resolves next to the suite)
.PHONY: test t

test:
	pymickey pymickey_tests/test_login.mickey.yaml

t: test
