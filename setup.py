from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read().splitlines()

setup(
    name="thinkrealty-service-client",
    version="0.1.0",
    author="ThinkRealty Engineering",
    author_email="engineering@thinkrealty.ae",
    description="Service-to-service communication client for ThinkRealty microservices",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=['service_client'],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-asyncio>=0.15.0",
            "black>=21.0.0",
            "mypy>=0.910",
        ],
    },
)
