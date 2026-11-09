# apiary's GDScript test runner (written by `apiary gamedev godot-tests`). Run it headless:
#     godot --headless --path <project> --script res://tests/run_tests.gd [-- --files res://tests/a.gd,res://tests/b.gd]
# It runs every test_* method in every res://tests/**/test_*.gd (or only the --files given), prints one line per test
# ("PASS res://tests/x.gd::test_name") and a summary, and quits with 0 only if at least one test ran and every test
# passed. Needs Godot 4.5 or later (it uses Logger).
# Measured with Godot 4.7.2: a runtime error aborts the test method but the caller carries on, so without the
# logger a crashed test would look like a pass. The logger counts errors per test; any error fails that test.
# Godot also prints SCRIPT ERROR, which the godot connector's error_patterns fail on (spec C-6).
extends SceneTree

const TESTS_DIR := "res://tests"


class ErrorCounter extends Logger:
	var count := 0
	var last := ""

	func _log_error(function: String, file: String, line: int, code: String, rationale: String,
			_editor_notify: bool, _error_type: int, _script_backtraces: Array[ScriptBacktrace]) -> void:
		count += 1
		last = "%s (%s:%d %s)" % [rationale if rationale else code, file, line, function]

	func _log_message(_message: String, _error: bool) -> void:
		pass


func _find(dir: String, out: Array[String]) -> void:
	for f in DirAccess.get_files_at(dir):
		if f.begins_with("test_") and f.ends_with(".gd"):
			out.append(dir + "/" + f)
	for d in DirAccess.get_directories_at(dir):
		_find(dir + "/" + d, out)


func _initialize() -> void:
	var errors := ErrorCounter.new()
	OS.add_logger(errors)
	var passed := 0
	var failed := 0
	var paths: Array[String] = []
	var args := OS.get_cmdline_user_args()
	var only := args.find("--files")
	if only >= 0 and only + 1 < args.size():
		for p in args[only + 1].split(",", false):
			paths.append(p.strip_edges())
	else:
		_find(TESTS_DIR, paths)
	paths.sort()
	if paths.is_empty():
		print("APIARY-TESTS: no tests found in %s (files named test_*.gd)" % TESTS_DIR)
		quit(1)
		return
	for path in paths:
		var before_load := errors.count
		var script: GDScript = load(path) if ResourceLoader.exists(path) else null
		if script == null or not script.can_instantiate() or errors.count > before_load:
			print("FAIL %s: does not load (parse error?)" % path)
			failed += 1
			continue
		for m in script.get_script_method_list():
			var method: String = m["name"]
			if not method.begins_with("test_"):
				continue
			var case = script.new()
			var before := errors.count
			case.call(method)
			if errors.count > before:
				case.failures.append("runtime error: " + errors.last)
			if case.failures.is_empty():
				print("PASS %s::%s (%d checks)" % [path, method, case.checks])
				passed += 1
			else:
				print("FAIL %s::%s" % [path, method])
				for msg in case.failures:
					print("    " + msg)
				failed += 1
	print("APIARY-TESTS: %d passed, %d failed" % [passed, failed])
	quit(0 if failed == 0 and passed > 0 else 1)
