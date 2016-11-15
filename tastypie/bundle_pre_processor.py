from tastypie.exceptions import TastypieError, Unauthorized
import importlib


class BundlePreProcessor(object):
    """
    A base class that provides basic structure of what events are raised
    """

    def __get__(self, instance, owner):
        """
        Makes ``EventManager`` a descriptor of ``ResourceOptions`` and creates
        a reference to the ``ResourceOptions`` object that may be used by
        methods of ``BasicEventManager``.
        """
        self.resource_meta = instance
        return self

    #Get method processors
    def read_list(self, bundle):
        """
        Called before get_list is executed.
        object_list: list of authorized objects that can be read by the user
        bundle: plain bundle - does not have obj or data populated
        """
        return bundle

    def read_detail(self, bundle):
        """
        Called before dehydrate object is executed.
        object_list: list of authorized objects that can be read by the user
        bundle: bundle - bundle.obj is the object being requested. dehydration is not yet called
        """

        return bundle

    #Post method processors
    '''
    #Not implemented currently
    def create_list(self, bundle):
        pass
    '''

    def create_detail(self, bundle):
        return bundle

    #put method processors
    def update_detail(self, bundle):
        return bundle

    def update_list(self, bundle):
        return bundle

    #delete method processors
    def delete_list(self, bundle):
        return bundle

    def delete_detail(self, bundle):
        return bundle


class MultiProcessor(BundlePreProcessor):

    def __init__(self, pre_processors=[], *args, **kwargs):
        self.pre_processors = pre_processors
        self._pre_processors = None
        super(MultiProcessor,self).__init__(*args, **kwargs)

    def resolve_class_by_name(self, cls_path):
        if not isinstance(cls_path , basestring):
            return cls_path
        # It's a string. Let's figure it out.
        if '.' in cls_path:
            # Try to import.
            module_bits = cls_path.split('.')
            module_path, class_name = '.'.join(module_bits[:-1]), module_bits[-1]
            module = importlib.import_module(module_path)
        else:
            # We've got a bare class name here, which won't work (No AppCache
            # to rely on). Try to throw a useful error.
            raise ImportError("Tastypie requires a Python-style path (<module.module.Class>) to lazy load event processors. Only given '%s'." % self.to)

        cls = getattr(module, class_name, None)

        if cls is None:
            raise ImportError("Module '%s' does not appear to have a class called '%s'." % (module_path, class_name))
        return cls

    def get_pre_processors(self):
        if not self._pre_processors:
            self._pre_processors =  [self.resolve_class_by_name(cls) for cls in self.pre_processors]
        return self._pre_processors

    def read_list_processors(self):
        return self.get_pre_processors()

    def read_detail_processors(self):
        return self.get_pre_processors()

    def create_detail_processors(self):
        return self.get_pre_processors()

    def update_detail_processors(self):
        return self.get_pre_processors()

    def update_list_processors(self):
        return self.get_pre_processors()

    def delete_list_processors(self):
        return self.get_pre_processors()

    def delete_detail_processors(self):
        return self.get_pre_processors()

    def read_list(self, bundle):
        for event_handler in self.read_list_processors():
            bundle = event_handler.read_list(bundle)

        return bundle

    def read_detail(self, bundle):
        for event_handler in self.read_detail_processors():
            bundle = event_handler.read_detail(bundle)
        return bundle

    #Post method processors
    def create_detail(self, bundle):
        for ev in self.create_detail_processors():
            bundle = ev.create_detail(bundle)
        return bundle

    #put method processors
    def update_detail(self, bundle):
        for ev in self.update_detail_processors():
            bundle = ev.update_detail(bundle)
        return bundle

    def update_list(self, bundle):
        for ev in self.update_list_processors():
            bundle = ev.update_list(bundle)
        return bundle

    #delete method processors
    def delete_list(self, bundle):
        for ev in self.delete_list_processors():
            bundle = ev.delete_list(bundle)
        return bundle

    def delete_detail(self, bundle):
        for ev in self.delete_detail_processors():
            bundle = ev.delete_detail(bundle)
        return bundle
