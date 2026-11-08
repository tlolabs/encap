The graph reference is copied unchanged from AVID Core v0.3.2 commit
`8296a9e623c6924c12e456b5fe9e7c10b59dfbde`, `tests/fixtures/encap-graph.txt`
(GPL-3.0-or-later). It is a test expectation, not a Core implementation or runtime
asset. Keeping it here isolates EnCAP tests from concurrent sibling refactors.
The graph includes square-pixel artwork normalization; the fake media tools
advertise the `setsar` filter used by this reference.
