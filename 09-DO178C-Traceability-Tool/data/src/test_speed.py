# Sample source tree for the traceability scan.


# @req REQ-017
def test_speed_limit_warning():
    """This test claims REQ-017, which is not in the requirements file.

    Someone deleted or renumbered the requirement and left the test
    behind. From the requirements side everything still looks traced,
    which is why the scan reads the code back."""
