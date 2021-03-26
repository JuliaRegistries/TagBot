using Pkg: Pkg, Registry, TOML

# TODO: Re-enable this when the build-time cost is worth the runtime savings.
# Pkg.add("PackageCompiler")
# using Dates: Day
# using PackageCompiler: create_sysimage
# TODO: precompile_execution_file
# create_sysimage(; replace_default=true, filter_stdlibs=true, incremental=false)
# rm("/opt/julia/lib/julia/sys.so.backup")
# Pkg.rm("PackageCompiler")
# Pkg.gc(; collect_delay=Day(0))

ENV["PYTHON"] = Sys.which("python")
Pkg.instantiate()
Registry.rm("General")
python_deps = collect(TOML.parsefile("Project.toml")["python"])
foreach(dep -> run(`pip install $(dep.first)==$(dep.second)`), python_deps)
