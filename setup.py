from setuptools import find_packages, setup


setup(
    name="pathscout",
    version="0.3.0",
    description="Local-first startup role discovery.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    license="MIT",
    packages=find_packages(include=["pathscout", "pathscout.*"]),
    entry_points={"console_scripts": ["pathscout=pathscout.cli:main"]},
)
