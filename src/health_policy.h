#ifndef IOSCAFFEINATE_HEALTH_POLICY_H
#define IOSCAFFEINATE_HEALTH_POLICY_H

#include "health.h"
#include "server_policy.h"

/* Copies raw observations for diagnostics. It never marks a P009 gate PASS. */
void health_apply_to_server_policy(const health_snapshot_t *snapshot,
                                   server_policy_inputs_t *inputs);

#endif
