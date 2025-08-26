# Home Assistant Intents Package

Packaging for [intents](https://github.com/home-assistant/intents/)


## Install

Clone the repo and create a virtual environment:

``` sh
git clone --recursive https://github.com/home-assistant/intents-package
cd intents-package
script/setup
```


## Package

Update the submodule:

``` sh
git submodule update --remote
```

Bump the version in `pyproject.toml` to `YYYY.M.D` and commit changes.

Generate dist:

``` sh
script/package
```

Upload `.tar.gz` and `.whl` in `dist/` to PyPI.

## Packaging to test changes

For E2E testing a Pull Request it may be useful to run locally a change from a fork.

Pre-requisite: you already cloned the repository following the instructions above.

1. Generate a package.

    ```sh
    cd intents
    git remote add username https://github.com/username/intents.git
    git fetch username
    git checkout branchname # in case you are not using main
    cd ..
    script/package
    ```

    You should see a new folder `/dist` with two files one `.whl` and one `.tar.gz`.
