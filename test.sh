#!/bin/sh

emit_config() {
  echo multigraph one
  echo "graph_title test with single word"
  echo "graph_category test"
  echo "test.label test"
  echo multigraph two
  echo "graph_title test with two words"
  echo "graph_category test"
  echo "test2.label test2"
}

emit_values() {
  echo multigraph one
  echo "test.value 121212"
  echo multigraph two
  echo "test2.value 454545"
}

emit_values_alone() {
  echo multigraph one
  echo "test.value 111111"
  echo multigraph two
  echo "test2.value 333333"
}

case "$1" in
  config)
    emit_config
    if [ "$MUNIN_CAP_DIRTYCONFIG" = "1" ]; then
      emit_values
    fi
    ;;
  *)
    emit_values_alone
    ;;
esac