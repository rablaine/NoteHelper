"""
AI routes for NoteHelper.
Handles AI-powered topic suggestion and related features.
"""
from flask import Blueprint, request, jsonify, g
from datetime import date
import json

from app.models import db, AIConfig, AIUsage, AIQueryLog, Topic

# Create blueprint
ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/api/ai/suggest-topics', methods=['POST'])
def api_ai_suggest_topics():
    """Generate topic suggestions from call notes using AI."""
    
    # Check if AI features are enabled
    ai_config = AIConfig.query.first()
    if not ai_config or not ai_config.enabled:
        return jsonify({'success': False, 'error': 'AI features are not enabled'}), 400
    
    if not ai_config.endpoint_url or not ai_config.api_key or not ai_config.deployment_name:
        return jsonify({'success': False, 'error': 'AI configuration is incomplete'}), 400
    
    # Get call notes from request
    data = request.get_json()
    call_notes = data.get('call_notes', '').strip()
    
    if not call_notes or len(call_notes) < 10:
        return jsonify({'success': False, 'error': 'Call notes are too short to analyze'}), 400
    
    # Check rate limit
    today = date.today()
    usage = AIUsage.query.filter_by(date=today).first()
    
    if not usage:
        usage = AIUsage( date=today, call_count=0)
        db.session.add(usage)
    
    if usage.call_count >= ai_config.max_daily_calls_per_user:
        return jsonify({
            'success': False,
            'error': 'Daily AI quota exceeded',
            'remaining': 0,
            'limit': ai_config.max_daily_calls_per_user
        }), 429
    
    # Make AI API call
    try:
        import requests
        
        # Azure AI Foundry Serverless API uses direct HTTP calls with Bearer auth
        full_url = ai_config.endpoint_url
        if not full_url.endswith('/chat/completions'):
            full_url = full_url.rstrip('/') + '/chat/completions'
        
        full_url = f"{full_url}?api-version={ai_config.api_version}"
        
        headers = {
            "Content-Type": "application/json",
            "api-key": ai_config.api_key
        }
        
        payload = {
            "messages": [
                {"role": "system", "content": ai_config.system_prompt},
                {"role": "user", "content": f"Call notes:\n\n{call_notes}"}
            ],
            "max_tokens": 150,
            "model": ai_config.deployment_name
        }
        
        response = requests.post(full_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result_data = response.json()
        
        # Log the full response structure for debugging
        full_response_debug = json.dumps(result_data, indent=2)[:2000]
        
        # Check if response has expected structure
        if 'choices' not in result_data or not result_data['choices']:
            raise ValueError(f"API response missing 'choices'. Full response:\n{full_response_debug}")
        
        if 'message' not in result_data['choices'][0] or 'content' not in result_data['choices'][0]['message']:
            raise ValueError(f"API response missing 'message.content'. Full response:\n{full_response_debug}")
        
        response_text = result_data['choices'][0]['message']['content']
        
        if not response_text or not response_text.strip():
            raise ValueError(f"API returned empty content. Full response:\n{full_response_debug}")
        
        response_text = response_text.strip()
        
        # Keep the raw response for logging
        raw_response_text = response_text
        
        # Extract token usage and model info
        model_used = result_data.get('model', ai_config.deployment_name)
        usage_data = result_data.get('usage', {})
        prompt_tokens = usage_data.get('prompt_tokens')
        completion_tokens = usage_data.get('completion_tokens')
        total_tokens = usage_data.get('total_tokens')
        
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
                request_text=call_notes[:1000],
                response_text=raw_response_text[:1000],  # Use raw response, not cleaned version
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
            request_text=call_notes[:1000],
            response_text=raw_response_text[:1000],  # Use raw response before parsing
            success=True,
            error_message=None,
            model=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )
        db.session.add(log_entry)
        
        # Increment usage counter
        usage.call_count += 1
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
                new_topic = Topic(name=topic_name)
                db.session.add(new_topic)
                db.session.flush()  # Get the ID
                topic_ids.append({'id': new_topic.id, 'name': new_topic.name})
        
        db.session.commit()
        
        remaining_calls = ai_config.max_daily_calls_per_user - usage.call_count
        
        return jsonify({
            'success': True,
            'topics': topic_ids,
            'remaining': remaining_calls,
            'limit': ai_config.max_daily_calls_per_user
        })
    
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                error_msg = f"{e.response.status_code} - {error_detail}"
            except:
                error_msg = f"{e.response.status_code} - {e.response.text}"
        
        # Log the error
        log_entry = AIQueryLog(
            request_text=call_notes[:1000],
            response_text=None,
            success=False,
            error_message=error_msg
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({'success': False, 'error': f'AI request failed: {error_msg}'}), 500
    
    except Exception as e:
        # Log failed query
        log_entry = AIQueryLog(
            request_text=call_notes[:1000],
            response_text=None,
            success=False,
            error_message=str(e)
        )
        db.session.add(log_entry)
        db.session.commit()
        
        error_msg = str(e)
        return jsonify({'success': False, 'error': f'AI request failed: {error_msg}'}), 500


@ai_bp.route('/api/ai/usage', methods=['GET'])
def api_ai_usage():
    """Get current user's AI usage for today."""
    ai_config = AIConfig.query.first()
    if not ai_config:
        return jsonify({'enabled': False})
    
    today = date.today()
    usage = AIUsage.query.filter_by(date=today).first()
    
    used = usage.call_count if usage else 0
    remaining = max(0, ai_config.max_daily_calls_per_user - used)
    
    return jsonify({
        'enabled': ai_config.enabled,
        'used': used,
        'remaining': remaining,
        'limit': ai_config.max_daily_calls_per_user
    })
