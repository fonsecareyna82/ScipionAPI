"""Matrix values of metadata, as the metadata viewer receives them."""
import json

import numpy as np
import pytest

from app.backend.utils.matrix_values import matrixForJson, parseMatrix

STORED = "[[1.0, 0.0, 0.0, -2504.25], [0.0, 1.0, 0.0, -2590.65], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]"


def test_a_stored_transform_is_a_4x4_matrix():
    assert matrixForJson(STORED) == [[1.0, 0.0, 0.0, -2504.25], [0.0, 1.0, 0.0, -2590.65],
                                     [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


@pytest.mark.parametrize("missing", [None, "", "  ", "None", "null", np.array([])])
def test_an_object_without_matrix_has_none(missing):
    assert matrixForJson(missing) is None


@pytest.mark.parametrize("text", ["[[nan, 0.0], [-inf, 1.0]]", "[[NaN, 0.0], [-Infinity, 1.0]]", "[[ nan  0.]\n [-inf  1.]]"])
def test_non_finite_entries_are_kept_as_text_that_json_carries(text):
    value = matrixForJson(text)
    assert value == [["NaN", 0.0], ["-Inf", 1.0]]
    json.dumps(value, allow_nan=False)


def test_numpy_print_format_and_arrays_are_read():
    assert matrixForJson("[[1. 0.]\n [0. 1.]]") == [[1.0, 0.0], [0.0, 1.0]]
    assert matrixForJson(np.eye(3)) == np.eye(3).tolist()
    assert matrixForJson([[1, 2], [3, 4]]) == [[1.0, 2.0], [3.0, 4.0]]


def test_vectors_and_rounding():
    assert matrixForJson("[1.0, 2.0, 3.0]") == [1.0, 2.0, 3.0]
    assert matrixForJson("[[0.123456, 1.0]]", decimals=3) == [[0.123, 1.0]]


def test_a_text_that_is_not_a_matrix_is_shown_as_it_is():
    assert parseMatrix("abc") is None
    assert matrixForJson("abc") == "abc"
