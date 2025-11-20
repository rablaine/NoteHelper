"""
Streaming import API for data management.
This file contains the import endpoint that streams progress updates.
"""
import csv
import json
import tempfile
import os
from flask import Response, stream_with_context


def create_import_endpoint(app, db, Territory, Seller, POD, SolutionEngineer, Vertical, Customer):
    """Create the streaming import endpoint."""
    
    @app.route('/api/data-management/import', methods=['POST'])
    def data_management_import():
        """Import alignment sheet CSV with real-time progress feedback."""
        from flask import request
        
        if 'file' not in request.files:
            return {'error': 'No file uploaded'}, 400
        
        file = request.files['file']
        
        if file.filename == '':
            return {'error': 'No file selected'}, 400
        
        if not file.filename.endswith('.csv'):
            return {'error': 'File must be a CSV'}, 400
        
        def generate():
            """Generator function to stream progress updates."""
            temp_path = None
            try:
                # Send progress message
                yield "data: " + json.dumps({"message": "Saving uploaded file..."}) + "\n\n"
                
                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.csv') as temp_file:
                    file.save(temp_file.name)
                    temp_path = temp_file.name
                
                yield "data: " + json.dumps({"message": "Reading CSV file..."}) + "\n\n"
                
                # Read CSV with multiple encoding attempts
                encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
                rows = None
                
                for encoding in encodings:
                    try:
                        with open(temp_path, 'r', encoding=encoding) as f:
                            reader = csv.DictReader(f)
                            rows = list(reader)
                        msg = f"Successfully read CSV with {encoding} encoding ({len(rows)} rows)"
                        yield "data: " + json.dumps({"message": msg}) + "\n\n"
                        break
                    except UnicodeDecodeError:
                        continue
                
                if rows is None:
                    yield "data: " + json.dumps({"error": "Could not read CSV file"}) + "\n\n"
                    return
                
                # Track created entities
                territories_map = {}
                sellers_map = {}
                pods_map = {}
                solution_engineers_map = {}
                verticals_map = {}
                
                yield "data: " + json.dumps({"message": "Processing territories..."}) + "\n\n"
                
                # Create Territories
                territory_names = set(row.get('Sales Territory', '').strip() for row in rows if row.get('Sales Territory', '').strip())
                for territory_name in territory_names:
                    existing = Territory.query.filter_by(name=territory_name).first()
                    if existing:
                        territories_map[territory_name] = existing
                    else:
                        territory = Territory(name=territory_name)
                        db.session.add(territory)
                        territories_map[territory_name] = territory
                
                db.session.flush()
                msg = f"Created/found {len(territories_map)} territories"
                yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Processing sellers..."}) + "\n\n"
                
                # Create Sellers
                seller_names = set(row.get('DSS (Growth/Acq)', '').strip() for row in rows if row.get('DSS (Growth/Acq)', '').strip())
                for seller_name in seller_names:
                    existing = Seller.query.filter_by(name=seller_name).first()
                    if existing:
                        sellers_map[seller_name] = existing
                    else:
                        seller_row = next((r for r in rows if r.get('DSS (Growth/Acq)', '').strip() == seller_name), None)
                        if seller_row:
                            growth_dss = seller_row.get('Primary Cloud & AI DSS', '').strip()
                            acq_dss = seller_row.get('Primary Cloud & AI-Acq DSS', '').strip()
                            
                            if growth_dss:
                                seller_type = 'Growth'
                                alias = growth_dss.lower()
                            elif acq_dss:
                                seller_type = 'Acquisition'
                                alias = acq_dss.lower()
                            else:
                                seller_type = 'Growth'
                                alias = None
                            
                            seller = Seller(name=seller_name, seller_type=seller_type, alias=alias)
                            db.session.add(seller)
                            sellers_map[seller_name] = seller
                
                db.session.flush()
                msg = f"Created/found {len(sellers_map)} sellers"
                yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Associating sellers with territories..."}) + "\n\n"
                
                # Associate Sellers with Territories
                for row in rows:
                    seller_name = row.get('DSS (Growth/Acq)', '').strip()
                    territory_name = row.get('Sales Territory', '').strip()
                    if seller_name and territory_name:
                        seller = sellers_map.get(seller_name)
                        territory = territories_map.get(territory_name)
                        if seller and territory and territory not in seller.territories:
                            seller.territories.append(territory)
                
                db.session.flush()
                yield "data: " + json.dumps({"message": "Seller-territory associations complete"}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Processing PODs..."}) + "\n\n"
                
                # Create PODs
                pod_names = set(row.get('SME&C POD', '').strip() for row in rows if row.get('SME&C POD', '').strip())
                for pod_name in pod_names:
                    existing = POD.query.filter_by(name=pod_name).first()
                    if existing:
                        pods_map[pod_name] = existing
                    else:
                        pod = POD(name=pod_name)
                        db.session.add(pod)
                        pods_map[pod_name] = pod
                
                db.session.flush()
                msg = f"Created/found {len(pods_map)} PODs"
                yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Associating territories with PODs..."}) + "\n\n"
                
                # Associate Territories with PODs
                for territory_name, territory in territories_map.items():
                    territory_row = next((r for r in rows if r.get('Sales Territory', '').strip() == territory_name), None)
                    if territory_row:
                        pod_name = territory_row.get('SME&C POD', '').strip()
                        if pod_name and not territory.pod:
                            territory.pod = pods_map.get(pod_name)
                
                db.session.flush()
                yield "data: " + json.dumps({"message": "Territory-POD associations complete"}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Processing solution engineers (Data)..."}) + "\n\n"
                
                # Create Solution Engineers - Data
                data_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
                for row in rows:
                    se_name = row.get('Data SE', '').strip()
                    if se_name:
                        if se_name not in data_se_info:
                            alias = row.get('Primary Cloud & AI Data DSE', '').strip().lower()
                            data_se_info[se_name] = {'alias': alias, 'pods': set()}
                        pod_name = row.get('SME&C POD', '').strip()
                        if pod_name and pod_name in pods_map:
                            data_se_info[se_name]['pods'].add(pod_name)
                
                for se_name, info in data_se_info.items():
                    existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Data').first()
                    if existing:
                        solution_engineers_map[se_name] = existing
                        # Update POD associations for existing SE
                        for pod_name in info['pods']:
                            pod = pods_map.get(pod_name)
                            if pod and pod not in existing.pods:
                                existing.pods.append(pod)
                    else:
                        se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Data')
                        for pod_name in info['pods']:
                            se.pods.append(pods_map[pod_name])
                        db.session.add(se)
                        solution_engineers_map[se_name] = se
                
                yield "data: " + json.dumps({"message": "Processing solution engineers (Infra)..."}) + "\n\n"
                
                # Create Solution Engineers - Infra
                infra_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
                for row in rows:
                    se_name = row.get('Infra SE', '').strip()
                    if se_name:
                        if se_name not in infra_se_info:
                            alias = row.get('Primary Cloud & AI Infrastructure DSE', '').strip().lower()
                            infra_se_info[se_name] = {'alias': alias, 'pods': set()}
                        pod_name = row.get('SME&C POD', '').strip()
                        if pod_name and pod_name in pods_map:
                            infra_se_info[se_name]['pods'].add(pod_name)
                
                for se_name, info in infra_se_info.items():
                    existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Core and Infra').first()
                    if existing:
                        solution_engineers_map[se_name] = existing
                        # Update POD associations for existing SE
                        for pod_name in info['pods']:
                            pod = pods_map.get(pod_name)
                            if pod and pod not in existing.pods:
                                existing.pods.append(pod)
                    else:
                        se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Core and Infra')
                        for pod_name in info['pods']:
                            se.pods.append(pods_map[pod_name])
                        db.session.add(se)
                        solution_engineers_map[se_name] = se
                
                yield "data: " + json.dumps({"message": "Processing solution engineers (Apps)..."}) + "\n\n"
                
                # Create Solution Engineers - Apps
                apps_se_info = {}  # {se_name: {'alias': str, 'pods': set()}}
                for row in rows:
                    se_name = row.get('Apps SE', '').strip()
                    if se_name:
                        if se_name not in apps_se_info:
                            alias = row.get('Primary Cloud & AI Apps DSE', '').strip().lower()
                            apps_se_info[se_name] = {'alias': alias, 'pods': set()}
                        pod_name = row.get('SME&C POD', '').strip()
                        if pod_name and pod_name in pods_map:
                            apps_se_info[se_name]['pods'].add(pod_name)
                
                for se_name, info in apps_se_info.items():
                    existing = SolutionEngineer.query.filter_by(name=se_name, specialty='Azure Apps and AI').first()
                    if existing:
                        solution_engineers_map[se_name] = existing
                        # Update POD associations for existing SE
                        for pod_name in info['pods']:
                            pod = pods_map.get(pod_name)
                            if pod and pod not in existing.pods:
                                existing.pods.append(pod)
                    else:
                        se = SolutionEngineer(name=se_name, alias=info['alias'] if info['alias'] else None, specialty='Azure Apps and AI')
                        for pod_name in info['pods']:
                            se.pods.append(pods_map[pod_name])
                        db.session.add(se)
                        solution_engineers_map[se_name] = se
                
                db.session.flush()
                msg = f"Created/found {len(solution_engineers_map)} solution engineers"
                yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Processing verticals..."}) + "\n\n"
                
                # Create Verticals - collect all unique vertical names from both columns
                vertical_names = set()
                for row in rows:
                    vertical = row.get('Vertical', '').strip()
                    category = row.get('Vertical Category', '').strip()
                    # Add Vertical if not N/A
                    if vertical and vertical.upper() != 'N/A':
                        vertical_names.add(vertical)
                    # Add Vertical Category as separate vertical if not N/A
                    if category and category.upper() != 'N/A':
                        vertical_names.add(category)
                
                for vertical_name in vertical_names:
                    existing = Vertical.query.filter_by(name=vertical_name).first()
                    if existing:
                        verticals_map[vertical_name] = existing
                    else:
                        vertical = Vertical(name=vertical_name)
                        db.session.add(vertical)
                        verticals_map[vertical_name] = vertical
                
                db.session.flush()
                msg = f"Created/found {len(verticals_map)} verticals"
                yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Processing customers..."}) + "\n\n"
                
                # Create Customers
                customers_created = 0
                customers_skipped = 0
                total_rows = len(rows)
                
                for idx, row in enumerate(rows, 1):
                    customer_name = row.get('Customer Name', '').strip()
                    tpid_str = row.get('TPID', '').strip()
                    
                    if not customer_name or not tpid_str:
                        customers_skipped += 1
                        continue
                    
                    try:
                        tpid = int(tpid_str)
                    except ValueError:
                        customers_skipped += 1
                        continue
                    
                    existing = Customer.query.filter_by(tpid=tpid).first()
                    if existing:
                        customers_skipped += 1
                        continue
                    
                    territory_name = row.get('Sales Territory', '').strip()
                    seller_name = row.get('DSS (Growth/Acq)', '').strip()
                    vertical_name = row.get('Vertical', '').strip()
                    category = row.get('Vertical Category', '').strip()
                    
                    customer = Customer(
                        name=customer_name,
                        tpid=tpid,
                        territory=territories_map.get(territory_name),
                        seller=sellers_map.get(seller_name)
                    )
                    
                    # Associate both verticals if they exist and aren't N/A
                    if vertical_name and vertical_name.upper() != 'N/A':
                        vertical = verticals_map.get(vertical_name)
                        if vertical:
                            customer.verticals.append(vertical)
                    
                    if category and category.upper() != 'N/A':
                        vertical = verticals_map.get(category)
                        if vertical and vertical not in customer.verticals:
                            customer.verticals.append(vertical)
                    
                    db.session.add(customer)
                    customers_created += 1
                    
                    # Progress update every 50 customers
                    if idx % 50 == 0:
                        msg = f"Processed {idx}/{total_rows} rows ({customers_created} created, {customers_skipped} skipped)"
                        yield "data: " + json.dumps({"message": msg}) + "\n\n"
                
                yield "data: " + json.dumps({"message": "Committing changes to database..."}) + "\n\n"
                db.session.commit()
                
                # Clean up temp file
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                
                # Send final success message
                result = {
                    'pods': len(pods_map),
                    'territories': len(territories_map),
                    'sellers': len(sellers_map),
                    'solution_engineers': len(solution_engineers_map),
                    'verticals': len(verticals_map),
                    'customers_created': customers_created,
                    'customers_skipped': customers_skipped
                }
                yield "data: " + json.dumps({"message": "Import complete!", "result": result}) + "\n\n"
                
            except Exception as e:
                db.session.rollback()
                # Clean up temp file on error
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                yield "data: " + json.dumps({"error": str(e)}) + "\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
