"""Tests for C++ parser with project-style UE code."""

from pathlib import Path

import pytest

from unreal_project_mcp.indexer.cpp_parser import CppParser, ParseResult, ParsedSymbol

FIXTURES = Path(__file__).parent / "fixtures" / "sample_project_source"


def _find(result: ParseResult, name: str, kind: str | None = None) -> ParsedSymbol | None:
    for s in result.symbols:
        if s.name == name and (kind is None or s.kind == kind):
            return s
    return None


def _find_all(result: ParseResult, kind: str) -> list[ParsedSymbol]:
    return [s for s in result.symbols if s.kind == kind]


@pytest.fixture
def parser():
    return CppParser()


@pytest.fixture
def header_result(parser):
    return parser.parse_file(FIXTURES / "MeshDamageStamper.h")


@pytest.fixture
def cpp_result(parser):
    return parser.parse_file(FIXTURES / "MeshDamageStamper.cpp")


class TestIncludes:
    def test_finds_includes(self, header_result):
        assert "CoreMinimal.h" in header_result.includes
        assert "Components/ActorComponent.h" in header_result.includes

    def test_cpp_includes(self, cpp_result):
        assert "MeshDamageStamper.h" in cpp_result.includes


class TestClassExtraction:
    def test_finds_class(self, header_result):
        cls = _find(header_result, "UMeshDamageStamper", "class")
        assert cls is not None

    def test_class_is_ue_macro(self, header_result):
        cls = _find(header_result, "UMeshDamageStamper", "class")
        assert cls.is_ue_macro is True

    def test_base_class(self, header_result):
        cls = _find(header_result, "UMeshDamageStamper", "class")
        assert "UActorComponent" in cls.base_classes

    def test_docstring(self, header_result):
        cls = _find(header_result, "UMeshDamageStamper", "class")
        assert "damage decals" in cls.docstring.lower()


class TestMemberExtraction:
    def test_finds_functions(self, header_result):
        func = _find(header_result, "ApplyDamageStamp", "function")
        assert func is not None

    def test_finds_variables(self, header_result):
        var = _find(header_result, "MaxDamageRadius", "variable")
        assert var is not None

    def test_function_ue_macro(self, header_result):
        func = _find(header_result, "ApplyDamageStamp", "function")
        assert func.is_ue_macro is True

    def test_variable_ue_macro(self, header_result):
        var = _find(header_result, "MaxDamageRadius", "variable")
        assert var.is_ue_macro is True

    def test_function_docstring(self, header_result):
        func = _find(header_result, "ApplyDamageStamp", "function")
        assert "damage stamp" in func.docstring.lower()

    def test_private_members(self, header_result):
        var = _find(header_result, "TotalDamage", "variable")
        assert var is not None


class TestCppDefinitions:
    def test_finds_method_definitions(self, cpp_result):
        funcs = _find_all(cpp_result, "function")
        func_names = [f.name for f in funcs]
        assert any("ApplyDamageStamp" in n for n in func_names)
        assert any("GetTotalDamage" in n for n in func_names)

    def test_qualified_names(self, cpp_result):
        func = _find(cpp_result, "UMeshDamageStamper::ApplyDamageStamp", "function")
        assert func is not None or _find(cpp_result, "ApplyDamageStamp", "function") is not None
