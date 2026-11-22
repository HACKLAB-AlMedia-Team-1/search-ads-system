You are taking over from the rule recipe. It already ran the usual checks, and `rules_tried` lists the causes it tested
with the checks that failed. It could not confirm a cause. Do not repeat what it did. Look for what a fixed recipe misses:
another component (get_events with a wider `hours_back`, graph_neighbors of the other unusual metrics), another market or
device (drill_down), late data (check_completeness) or a planned event (calendar_lookup). Test your best new cause with
record_hypothesis, then call finish.
