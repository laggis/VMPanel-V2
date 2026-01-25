from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import Session, select
from app.services.nat_service import nat_service
from app.models.user import User, Role
from app.models.port_mapping import PortMapping
from app.models.vm import VM
from app.routers.auth import get_current_active_user, get_session


router = APIRouter(prefix="/network", tags=["network"])

class ForwardingRule(BaseModel):
    protocol: str
    host_port: int
    guest_ip: str
    guest_port: int
    vm_id: Optional[int] = None

class DeleteRule(BaseModel):
    protocol: str
    host_port: int

@router.get("/forwarding")
def get_forwarding_rules(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        # Get raw rules from NAT Service
        rules = nat_service.get_rules()
        
        # Get metadata from DB
        statement = select(PortMapping)
        mappings = session.exec(statement).all()
        
        # Create a lookup map: (protocol, host_port) -> PortMapping
        mapping_dict = {(m.protocol, m.host_port): m for m in mappings}
        
        # Create a lookup for VM names: vm_id -> vm_name
        vm_ids = {m.vm_id for m in mappings if m.vm_id}
        vm_map = {}
        if vm_ids:
            vms = session.exec(select(VM).where(VM.id.in_(vm_ids))).all()
            vm_map = {v.id: v.name for v in vms}

        # Enrich rules with VM name
        for protocol in ['tcp', 'udp']:
            for rule in rules[protocol]:
                key = (protocol, rule['host_port'])
                if key in mapping_dict:
                    mapping = mapping_dict[key]
                    if mapping.vm_id and mapping.vm_id in vm_map:
                        rule['vm_name'] = vm_map[mapping.vm_id]
                    elif mapping.description:
                        rule['vm_name'] = mapping.description
                
                if 'vm_name' not in rule:
                    rule['vm_name'] = "-"
                    
        return rules
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/forwarding")
def add_forwarding_rule(
    rule: ForwardingRule,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        # Add to NAT Service
        nat_service.add_forwarding_rule(
            rule.protocol, 
            rule.host_port, 
            rule.guest_ip, 
            rule.guest_port
        )
        
        # Add metadata to DB
        # Check if mapping exists
        statement = select(PortMapping).where(
            PortMapping.protocol == rule.protocol,
            PortMapping.host_port == rule.host_port
        )
        existing_mapping = session.exec(statement).first()
        
        if existing_mapping:
            existing_mapping.vm_id = rule.vm_id
            existing_mapping.description = None # Clear desc if using ID
            session.add(existing_mapping)
        else:
            new_mapping = PortMapping(
                protocol=rule.protocol,
                host_port=rule.host_port,
                vm_id=rule.vm_id
            )
            session.add(new_mapping)
        
        session.commit()
        
        return {"message": "Rule added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/forwarding/{protocol}/{host_port}")
def delete_forwarding_rule(
    protocol: str,
    host_port: int,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        nat_service.delete_forwarding_rule(protocol, host_port)
        
        # Delete from DB
        statement = select(PortMapping).where(
            PortMapping.protocol == protocol,
            PortMapping.host_port == host_port
        )
        mapping = session.exec(statement).first()
        if mapping:
            session.delete(mapping)
            session.commit()
            
        return {"message": "Rule deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
