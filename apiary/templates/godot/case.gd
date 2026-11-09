# Base class for apiary's GDScript tests (written by `apiary gamedev godot-tests`; no add-on needed).
# A test file is res://tests/test_<name>.gd:
#     extends "res://tests/case.gd"
#     func test_jump_height():
#         check_eq(Player.new().jump_height(), 64, "jump height")
# Every method whose name starts with test_ runs once. A check that fails records a message; the test carries on.
extends RefCounted

var failures: Array[String] = []
var checks := 0


func check(condition: bool, message: String = "check failed") -> void:
	checks += 1
	if not condition:
		failures.append(message)


func check_eq(actual, expected, message: String = "") -> void:
	checks += 1
	if typeof(actual) != typeof(expected) or actual != expected:
		failures.append("%s: expected %s, got %s" % [message if message else "check_eq", str(expected), str(actual)])


func check_near(actual: float, expected: float, tolerance: float = 0.001, message: String = "") -> void:
	checks += 1
	if absf(actual - expected) > tolerance:
		failures.append("%s: expected %s +/- %s, got %s" % [message if message else "check_near", expected, tolerance, actual])


## The script at `path`, or null with a failure recorded. Tests reach the code under test through this (or make())
## instead of preload() or class_name, so a test written before its code fails when run instead of failing to parse.
func script_at(path: String) -> GDScript:
	checks += 1
	var s: GDScript = load(path) if ResourceLoader.exists(path) else null
	if s == null:
		failures.append("not implemented yet: %s" % path)
	return s


## A new instance of the script at `path` (constructor arguments in `args`), or null with a failure recorded.
func make(path: String, args: Array = []):
	var s := script_at(path)
	return s.callv("new", args) if s != null else null


func check_loads(path: String, message: String = "") -> Resource:
	checks += 1
	var res: Resource = load(path) if ResourceLoader.exists(path) else null
	if res == null:
		failures.append("%s: cannot load %s" % [message if message else "check_loads", path])
	return res
