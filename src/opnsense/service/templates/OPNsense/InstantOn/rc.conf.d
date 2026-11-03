{% if helpers.exists('OPNsense.instanton.general.enabled') and OPNsense.instanton.general.enabled == '1' %}
instanton_enable="YES"
{% else %}
instanton_enable="NO"
{% endif %}
