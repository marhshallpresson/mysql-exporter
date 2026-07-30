from setuptools import setup
setup(
    name='mysql-exporter',
    version='1.0.0',
    py_modules=['app'],
    install_requires=['flask', 'mysql-connector-python'],
)
