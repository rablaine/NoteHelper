"""
AI routes for NoteHelper.
Handles AI-powered topic suggestion and related features.
Uses Azure OpenAI with Entra ID (Service Principal) authentication.
"""
from flask import Blueprint, request, jsonify, g
from datetime import date
import json
import os

from app.models import db, AIConfig, AIQueryLog, Topic

# Create blueprint
ai_bp = Blueprint('ai', __name__)


def get_azure_openai_client(ai_config):
    """Create an Azure OpenAI client with Entra ID authentication."""
    from openai import AzureOpenAI
    from azure.identity import ClientSecretCredential, get_bearer_token_provider
    
    # Get service principal credentials from environment
    client_id = os.environ.get('AZURE_CLIENT_ID')
    client_secret = os.environ.get('AZURE_CLIENT_SECRET')
    tenant_id = os.environ.get('AZURE_TENANT_ID')
    
    if not all([client_id, client_secret, tenant_id]):
        raise ValueError("Missing Azure service principal environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)")
    
    # Create credential and token provider
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret
    )
    token_provider = get_bearer_token_provider(
        credential, 
        "https://cognitiveservices.azure.com/.default"
    )
    
    # Create Azure OpenAI client
    client = AzureOpenAI(
        api_version=ai_config.api_version,
        azure_endpoint=ai_config.endpoint_url,
        azure_ad_token_provider=token_provider,
    )
    
    return client


@ai_bp.route('/api/ai/suggest-topics', methods=['POST'])
def api_ai_suggest_topics():
    """Generate topic suggestions from call notes using AI."""
    
    # Check if AI features are enabled
    ai_config = AIConfig.query.first()
    if not ai_config or not ai_config.enabled:
        return jsonify({'success': False, 'error': 'AI features are not enabled'}), 400
    
    if not ai_config.endpoint_url or not ai_config.deployment_name:
        return jsonify({'success': False, 'error': 'AI configuration is incomplete (missing endpoint or deployment name)'}), 400
    
    # Get call notes from request
    data = request.get_json()
    call_notes = data.get('call_notes', '').strip()
    
    if not call_notes or len(call_notes) < 10:
        return jsonify({'success': False, 'error': 'Call notes are too short to analyze'}), 400
    
    # Make AI API call
    try:
        client = get_azure_openai_client(ai_config)
        
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": ai_config.system_prompt},
                {"role": "user", "content": f"Call notes:\n\n{call_notes}"}
            ],
            max_tokens=150,
            model=ai_config.deployment_name
        )
        
        response_text = response.choices[0].message.content
        
        if not response_text or not response_text.strip():
            raise ValueError("AI returned empty content")
        
        response_text = response_text.strip()
        
        # Keep the raw response for logging
        raw_response_text = response_text
        
        # Extract token usage and model info
        model_used = response.model or ai_config.deployment_name
        prompt_tokens = response.usage.prompt_tokens if response.usage else None
        completion_tokens = response.usage.completion_tokens if response.usage else None
        total_tokens = response.usage.total_tokens if response.usage else None
        
        # Parse JSON response - be flexible with different formats
        suggested_topics = []
        try:
            # Remove markdown code blocks if present
            clean_text = response_text
            if '```' in clean_text:
                # Extract content between code blocks
                import re
                match = re.search(r'```(?:json)?\s*(.*?)\s*```', clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(1).strip()
                else:
                    # Try to find just the JSON array
                    clean_text = clean_text.replace('```json', '').replace('```', '').strip()
            
            # Try to find a JSON array in the text
            import re
            array_match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            if array_match:
                clean_text = array_match.group(0)
            
            suggested_topics = json.loads(clean_text)
            
            if not isinstance(suggested_topics, list):
                raise ValueError("Response is not a list")
            
            # Filter to strings only and clean up
            suggested_topics = [str(t).strip() for t in suggested_topics if t and str(t).strip()]
            
            if not suggested_topics:
                raise ValueError("No topics returned")
            
        except (json.JSONDecodeError, ValueError) as e:
            # Log malformed response with full details for debugging
            log_entry = AIQueryLog(
                user_id=g.user.id,
                request_text=call_notes[:1000],
                response_text=raw_response_text[:1000],
                success=False,
                error_message=f"Parse error: {str(e)}",
                model=model_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens
            )
            db.session.add(log_entry)
            db.session.commit()
            return jsonify({
                'success': False,
                'error': f'AI returned invalid response format. Check audit log for raw response.'
            }), 500
        
        # Log successful query
        log_entry = AIQueryLog(
            user_id=g.user.id,
            request_text=call_notes[:1000],
            response_text=raw_response_text[:1000],
            success=True,
            error_message=None,
            model=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )
        db.session.add(log_entry)
        db.session.commit()
        
        # Process topics: check if they exist, if not create them, then return IDs
        topic_ids = []
        for topic_name in suggested_topics:
            # Check if topic exists (case-insensitive)
            existing_topic = Topic.query.filter(
                Topic.user_id == g.user.id,
                db.func.lower(Topic.name) == topic_name.lower()
            ).first()
            
            if existing_topic:
                topic_ids.append({'id': existing_topic.id, 'name': existing_topic.name})
            else:
                # Create new topic
                new_topic = Topic(name=topic_name, user_id=g.user.id)
                db.session.add(new_topic)
                db.session.flush()  # Get the ID
                topic_ids.append({'id': new_topic.id, 'name': new_topic.name})
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'topics': topic_ids
        })
    
    except Exception as e:
        # Log failed query
        error_msg = str(e)
        
        log_entry = AIQueryLog(
            user_id=g.user.id,
            request_text=call_notes[:1000],
            response_text=None,
            success=False,
            error_message=error_msg[:500]
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({'success': False, 'error': f'AI request failed: {error_msg}'}), 500



