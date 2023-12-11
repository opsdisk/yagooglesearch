import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="yagooglesearch",
    version="1.8.2",
    author="Brennon Thomas",
    author_email="info@opsdisk.com",
    description="A Python library for executing intelligent, realistic-looking, and tunable Google searches.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/opsdisk/yagooglesearch",
    packages=setuptools.find_packages(),
    package_data={
        "yagooglesearch": [
            "user_agents.txt",
            "result_languages.txt",
        ],
    },
    install_requires=[
        "beautifulsoup4>=4.9.3",
        "requests>=2.31.0",
        "requests[socks]",
    ],
    python_requires=">=3.6",
    license='BSD 3-Clause "New" or "Revised" License',
    keywords="python google search googlesearch",
)
