Clarifications

1. Good catch.  These are mistakes in the examples that dropped the intermediate `/envs/` sub-directory.  We want to keep umbrella's patterns.

2. The `umbrella` script is tailored to the specific and immediate needs of dune-xerosere development, thus the name "gcc15" has become default.  For the new `xerosere` script, I want to pick a more generic default environment name.  In fact, let's change the built-in default `env_name` from "xerosere" to "default" to make it even more emphatic.

3. take interpretation "a".  The super-build CMakeLists.txt looks already generic with the one exception of setting `XEROSERE_EXCLUDE`.  This was done for a specific reason at the time.  Continue to support `XEROSERE_EXCLUDE` in the body but for the copy of this CMakeLists.txt that we drop in, remove the line that sets it.

4. The CMake super build and `spack develop` are orthogonal ways to build the packages.  For now, let us defer support in the `xerosere` command until we get the more important features working.

5. For now, `dev repo add` just does the clone, respecting the `devel_root` configuration parameter.

6. Yes, exactly.  There is a phased parameter replacement followed by a final iterative interpolation phase.  The replacement phases:

Phase 0: The parameter set of built-in values.
Phase 1: Any matching shell environment variables replace values in the Phase 0 set.
Phase 2: XDG `~/.config/xerosere/config.toml` is read and parameters in each section replace Phase 1 set to make a new set for that section name.  We must carry each section.
Phase 3: local `.xerosere/config.toml` handled the same.  Each section here can override the corresponding Phase 2 parameter set of the same section name.
Phase 4: Each named Phase 3 parameter set overrides the phase 3 "DEFAULT" parameter set to become a new named parameter set.
Phase 5: Any parameters given on the command line override the same parameter in the Phase 4 named sets.

The iterative interpolation phase applies string interpolation to each phase 5 named parameter set individually until an iteration does not produce a new set of parameter values.  I do not foresee needing to have literal `{}`'s so any that remain after stability indicate an error that some parameter was not supplied.  Iteration should have an upper bound to guard against the user supplying recursively defined parameters.  It may need adjusting but I'd guess 10 iterations is ample even for highly self-referential parameter sets.

7. Yes, `[DEFAULT]` needs to be an application level idiom.  The `config_name` may not necessarily be provided in `[DEFAULT]`.  It could be provided as a shell environment variable or command line option.  The phased procedure from clarification 6 should allow for that and I think addresses the other questions for this item.

8. I confirm your interpretation.  A `-c/--config config.toml` file follows the local `.xerosere/config.toml` and precedes individual CLI options.

9. Yes, correct and acceptable.  Let's add `tomlkit` to the dependencies so we can preserve TOML comments. 

10. Good question.  Yes, make `config show` show the active parameter set.  We will defer any command that shows the full config with provenance.

11. For now, we will exclude the `deps` command.

12. Good find.  Yes, the config subsystem should provide these.  The tricky part is that the set of CMake parameters is somewhat open ended and `xerosere` will need to know which to translate into `-D<param>=<val>` type strings given to cmake.  And perhaps `xerosere` also needs to know which parameters are for cmake config vs build phases.  I am tempted to hoist all the TOML configuration sections to be in an `env` table.  For example `[env.DEFAULT]` or `[env.wcph]` and then invent a `[cmake.<name>]` convention which holds cmake variables.  Then an `[env.<name>]` table can have a `cmake_config` or a `cmake_build` variable each that names a `[cmake.<name>]`.  For shell environment variables, CMake will look directly for some, but maybe not all.  For CLI, we can reserve `-D` to define parameters and values to pass through to cmake.  More iteration on this item may be needed.

13. Yes, agreed.

14. Yes, keep the defensiveness.  There are also some spack-defenses in ../../.envrc governing Spack cache and config scope directories to avoid touching the user's `~/.spack/` directory, which is a major source of confusion and problems when the user uses spack in multiple locations.  Let's make these also canonical parameters, siblings to spack_root, etc.  They will need to be set in any shell environment that the `xerosere` spawns for, eg `subprocess.run()`.

15. Yes, we always use spack directory envs.  That is we would pass `-d/--dir` to `spack env create`.

16. Yes, fall back to `spack` from `$PATH`.

17. Yes, spelled "xerosere" https://en.wikipedia.org/wiki/Xerosere  My fingers sometimes mess up typing this unusual word.

18. Unless you know reasons otherwise, I think `tomlkit` is better as it allows read/write and preserves comments.

19. Yes, confirm.  



