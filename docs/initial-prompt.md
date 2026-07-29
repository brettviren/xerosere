# Design for a software development environment manager - xerosere

The dune-xerosere package introduced a Bash "umbrella" script to capture certain workflows on the assumption of the file tree layout of the dune-xerosere package.  The latest script is here:

https://raw.githubusercontent.com/brettviren/dune-xerosere/refs/heads/main/umbrella

This Python package "xerosere" generalizes this "umbrella" script to allow the patterns and workflows to be applied to other software development projects that are composed of multiple source repos and which have the flexibility to build and run using different "environments".  This new xerosere package is also generalized to leverage Spack installed locally in the development tree, Spack installed outside the tree, or using pixi to supply environments from conda package channels.  The common point is the "environment view directory" containing the conventional `view/{bin,lib,include}/` sub-directories and which all these sources can produce.

Like the "umbrella" script, the xerosere package will handle multiple git cloned repos being under mutual development.  It will help by constructing a "super build" CMakeLists.txt file for building all packages under development together and it will support using `spack devel` for the packages in development that have Spack recipes.

I give an example session that shows a list of the `xersere` sub-commands to be suported

```
# create and initalize "workdir" using a specifi config file
# This makes a workdir/.xerosere/ directory.  more on configuration below.
$ xeresere -c config.toml init workdir

# (Re)configure current working directory (no directory given) in an idempotent way
$ cd workdir/
$ xeresere init 

# Add a development package under the configured devel dir, taking the local source dir from the giturl
$ xeresere dev repo add <giturl>
# Same but use <dirname> for the directory name under the devel directory.
$ xeresere dev repo add <giturl> <dirname>

# Show the active configuration that would be used
$ xeresere config show 
# Show just the value of one parameter in the active configuration 
$ xeresere config get <param>
# Set a configuration parameter to the value in a local config.toml file in the active configuration section
$ xeresere config set <param> <value>
```

In addition, the existing commands should be ported from `umbrella` but with different command names:

- `umbrella concretize` --> `xerosere spack concretize`
- `umbrella install` --> `xerosere spack install`
- `umbrella config`  --> `xerosere dev config`
- `umbrella build`  --> `xerosere dev build`
- `umbrella test`  --> `xerosere test`

The "active configuration" is built by a chain of configuration sources.  For each parameter, the chain is walked and the last found wins in this order:

  - Builtin defaults set in the `xerosere` Python module
  - User shell environment variables
  - XDG located config file: `~/.config/xerosere/config.toml`
  - local directory config file: `.xerosere/config.toml`
  - CLI options

Configuration parameters and corresponding shell environment variables and CLI options follow a nomenclature.  

- Configuration file parameter names are lower cased and use underscore separators.
- Shell environment variable names prefix `XEROSERE_` to the upper-cased parameter name.
- CLI options are lower-cased parameter names with dashes replacing the underscore separators.

An initial list of parameters with built-in default values.  I will list spack-related and generic parameters.  Later we will extend to allow for the general parameters to mix with pixi-related parameters.

- `extern_root = "extern"` base of the "extern" tree (see below for relative path resolution)
- `extern_type = "spack"` or optionally "pixi", names how the development view directory is formed.
- `spack_root = "{extern_root}/spack"` location for a monolithic spack area including source and installation.
- `spack_exe = "{spack_root}/bin/spack"` location of spack executable.
- `spack_install = "{spack_root}/opt/spack"` location of spack install tree, same relative path interpretation.
- `spack_envs = "{extern_root}/envs"` base to hold envs
- `env_name = "xerosere"` name of the active env.
- `view_dir = "{spack_envs}/{env_name}/view"` a view directory (not spack specific, could point to a pixi env dir)
- `devel_root = "devel"` base for holding source repos that are under development
- `builds_root = "builds"` base for holding build outputs
- `env_build = "{builds_root}/{env_name}"` location receiving per-package build output when building in a particular env
- `installs_root = "installs"` root location for receiving installation of build of in-development packages
- `env_install = "{installs_root}/{env_name}"` location for installs made from a specific environment
- `config_name = "DEFAULT"` set which configuration file section to use


Relative path resolution: when a configuration supplies a path, and that path is relative, it is taken relative to the directory or the closest parent directory that contains a `.xerosere/` sub-directory.  This sub-directory may be made by `xerosere init` if not already existing.  It may be empty or hold `.xerosere/config.toml` that participates in the configuration chain just described.

Here are some example configuration files:

```toml
# ~/.config/xerosere/config.toml

[DEFAULT]  # Special, unammed section
env_name = default    # override built-in env_name
config_name = "wcph"  # set section to treat as active

[wcph]
env_name = "gcc15"

[pixi]    # After we add support to replace spack env views with pixi envs
extern_type = "pixi"

```

Here are some example command lines

```
# Configure based on built-in defaults, shell environment and ~/.config/xerosere/conf.toml
$ xerosere init my-default-area

# Further consider a given config file
$ xerosere --config custom.toml init my-new-working-area
$ cd my-new-working-area
$ xerosere init   # idempotent

# Show the active configureation
$ xerosere config show active

# Show the selected configuration by selecting [wcph] section
$ xerosere --config-name wcph config show active

# Get parameter value from active config 
$ xerosere config get <param> 

# Set parameter value in active config into .xerosere/config.toml
$ xerosere config set <param> <value>

# Ibid, but with explicitly activated config
$ xerosere --config-name wcph config set <param> <value>
$ XEROSERE_CONFIG_NAME=wcph xerosere config set <param> <value>

# Called like umbrella with changes noted as above
$ xerosere spack concretize
$ xerosere spack install 
$ xerosere dev config
$ xerosere dev build
$ xerosere test
```
