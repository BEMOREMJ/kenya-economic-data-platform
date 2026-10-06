{% test unique_combination(model, columns) %}

select
  {% for column in columns %}{{ column }}{% if not loop.last %}, {% endif %}{% endfor %},
  count(*) as duplicate_count
from {{ model }}
group by {% for column in columns %}{{ column }}{% if not loop.last %}, {% endif %}{% endfor %}
having count(*) > 1

{% endtest %}
