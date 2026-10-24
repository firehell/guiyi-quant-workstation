"""Exercise CLI startup ordering without credentials, network, or DB."""
import builtins
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parent
class FirstAppImport(Exception): pass

class StartupOrdering(unittest.TestCase):
    def check_entry(self,filename,apply,check_only=False):
        spec=importlib.util.spec_from_file_location('entry',BASE/filename)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        args=['entry']
        if 'resume' in filename:
            for key in ('inventory','plan','report','intent'):args += ['--'+key,'not-read','--'+key+'-sha256','0'*64]
            args += ['--original-writer-exited']
        else:args += ['--bundle','not-read','--bundle-sha256','0'*64,'--previous-writer-exited']
        if apply:args += ['--apply']
        if check_only:args += ['--check-only']
        private_required=apply or check_only
        boot=[]; original_import=builtins.__import__; original_spec=importlib.util.spec_from_file_location
        def spec_for(name,path,*a,**kw):
            if name=='private_boot':
                return SimpleNamespace(loader=SimpleNamespace(exec_module=lambda m:setattr(m,'bootstrap_private',lambda:boot.append(True))))
            return original_spec(name,path,*a,**kw)
        original_module=importlib.util.module_from_spec
        def module_for(spec):return SimpleNamespace() if not hasattr(spec,'name') else original_module(spec)
        def importing(name,*a,**kw):
            if name.startswith('app.'):
                self.assertEqual(bool(boot),private_required,'private configuration must precede application imports')
                if private_required:self.assertEqual(os.environ.get('GUIYI_PROJECT_ROOT'),str(module.RUNTIME))
                raise FirstAppImport()
            return original_import(name,*a,**kw)
        with patch.object(sys,'argv',args),patch.dict(os.environ,{},clear=False),patch.object(importlib.util,'spec_from_file_location',spec_for),patch.object(importlib.util,'module_from_spec',module_for),patch.object(builtins,'__import__',importing):
            with self.assertRaises(FirstAppImport):module.main()
        self.assertEqual(len(boot),int(private_required))
    def test_resume_apply_boots_before_app_imports(self):self.check_entry('v18-subing-native-resume-once.py',True)
    def test_advance_apply_boots_before_app_imports(self):self.check_entry('v18-subing-rb-advance-once.py',True)
    def test_resume_check_only_boots_before_app_imports(self):self.check_entry('v18-subing-native-resume-once.py',False,True)
    def test_advance_check_only_boots_before_app_imports(self):self.check_entry('v18-subing-rb-advance-once.py',False,True)
    def test_resume_plan_only_does_not_load_private_configuration(self):self.check_entry('v18-subing-native-resume-once.py',False)
    def test_advance_plan_only_does_not_load_private_configuration(self):self.check_entry('v18-subing-rb-advance-once.py',False)

if __name__=='__main__':unittest.main()
