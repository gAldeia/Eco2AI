from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

DEPENDENCIES = [
    "APScheduler",
    "pynvml>=5.6.2",
    "psutil",
    "py-cpuinfo",
]

setup(
    name = 'eco2ai',
    version = '0.1.1',
    author=["Vladimir Lazarev", 'Nikita Zakharenko', 'Semyon Budyonny', 'Leonid Zhukov'],
    url = 'http://37.18.73.175/applied-ai/Eco2AI.git@development',
    description = long_description,
    packages = find_packages(),
    install_requires=DEPENDENCIES,
    package_data={
        "eco2ai": [
            "data/cpu_names.csv",
            "data/config.txt"
        ]
    },
    include_package_data=True
)