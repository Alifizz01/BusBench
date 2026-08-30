/* Sample source tree for the traceability scan.
 * Annotations tie a test back to the requirement it proves. */

/* @req REQ-001 */
void test_brake_applies(void)
{
    /* engage the brake, check it happened inside 100 ms */
}

/* @req REQ-002 */
void test_brake_releases(void)
{
    /* clear the pedal signal, check the brake lets go */
}
