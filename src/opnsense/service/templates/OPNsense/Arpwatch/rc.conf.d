{% if helpers.exists('OPNsense.arpwatch.general.enabled') and OPNsense.arpwatch.general.enabled|default("0") == "1" %}
arpwatchd_enable="YES"
{% else %}
arpwatchd_enable="NO"
{% endif %}
