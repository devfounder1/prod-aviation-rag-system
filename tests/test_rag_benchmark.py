from evaluate_rag import grade, run_benchmark


def test_isolated_benchmark_retrieves_expected_sources() -> None:
    result = run_benchmark()
    assert result['passed'], result
    assert result['private_data_used'] is False


def test_grader_rejects_wrong_facts_citations_and_missing_abstention() -> None:
    case = {'expected_source': 'a.txt', 'facts': ['24'], 'abstain': False}
    result = grade(case, 'Power is 12 V from b.txt', ['b.txt'], ['b.txt'])
    assert not result['facts_present'] and not result['citation_correct'] and not result['retrieval_hit']
    assert not grade({'expected_source': None, 'facts': [], 'abstain': True},
                     'Weight is 10 kg', [], [])['abstention_correct']
