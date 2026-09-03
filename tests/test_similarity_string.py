from app.services.similarity.string_similarity import StringSimilarityChecker


def test_identical_text_has_similarity_1():
    checker = StringSimilarityChecker()
    assert checker.similarity("こんにちは世界", "こんにちは世界") == 1.0


def test_completely_different_text_has_low_similarity():
    checker = StringSimilarityChecker()
    assert checker.similarity("こんにちは世界", "全く別の内容です") < 0.5


def test_empty_string_has_similarity_0():
    checker = StringSimilarityChecker()
    assert checker.similarity("", "something") == 0.0
    assert checker.similarity("something", "") == 0.0


def test_backend_name_is_string():
    assert StringSimilarityChecker().backend_name == "string"
