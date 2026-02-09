# IDENTITY.md — Who Am I?

Name: {{ agent_name }}

Agent ID: {{ agent_id }}

Creature: {{ identity_role }}

Vibe: {{ identity_communication_style }}

Emoji: {{ identity_emoji }}

{% if identity_purpose %}
Purpose: {{ identity_purpose }}
{% endif %}

{% if identity_personality %}
Personality: {{ identity_personality }}
{% endif %}

{% if identity_custom_instructions %}
Custom Instructions:
{{ identity_custom_instructions }}
{% endif %}
