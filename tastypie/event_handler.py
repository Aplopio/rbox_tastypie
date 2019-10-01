from past.builtins import basestring
from builtins import object
from tastypie.exceptions import TastypieError, Unauthorized
import importlib


class EventHandler(object):
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

    def list_read(self, object_list, bundle):
        """
        Called after get_list is executed.
        object_list: list of authorized objects that can be read by the user
        bundle: plain bundle - does not have obj or data populated
        """
        pass

    def detail_read(self, object_list, bundle):
        """
        Called after dehydrate object is executed.
        object_list: list of authorized objects that can be read by the user
        bundle: bundle - bundle.obj is the object being requested. dehydration is already
        executed and bundle.data has dehydrated data
        """
        pass


    #Post method handlers
    '''
    #Not implemented currently
    def list_created(self, object_list, bundle):
        pass
    '''

    def list_action(self, object_list, bundle):
        pass

    def detail_action(self, object_list, bundle):
        pass

    def detail_created(self, object_list, bundle):
        pass

    #put method handlers
    def detail_updated(self, object_list, bundle):
        pass

    def list_updated(self, object_list, bundle):
        pass

    #delete method handlers
    def list_deleted(self, object_list, bundle):
        pass

    def detail_deleted(self, object_list, bundle):
        pass

    def pre_detail_deleted(self, object_list, bundle):
        pass


class MultiEventHandler(EventHandler):

    def __init__(self, event_handlers=None, *args, **kwargs):
        if event_handlers == None:
            event_handlers = []
        self.event_handlers = event_handlers
        self._event_handlers = None
        super(MultiEventHandler,self).__init__(*args, **kwargs)

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
            raise ImportError("Tastypie requires a Python-style path (<module.module.Class>) to lazy load event handlers. Only given '%s'." % self.to)

        cls = getattr(module, class_name, None)

        if cls is None:
            raise ImportError("Module '%s' does not appear to have a class called '%s'." % (module_path, class_name))
        return cls

    def get_event_handlers(self):
        if not self._event_handlers:
            self._event_handlers =  [self.resolve_class_by_name(cls) for cls in self.event_handlers]
        return self._event_handlers

    def read_list_handlers(self):
        return self.get_event_handlers()

    def read_detail_handlers(self):
        return self.get_event_handlers()

    def create_detail_handlers(self):
        return self.get_event_handlers()

    def update_detail_handlers(self):
        return self.get_event_handlers()

    def update_list_handlers(self):
        return self.get_event_handlers()

    def delete_list_handlers(self):
        return self.get_event_handlers()

    def delete_detail_handlers(self):
        return self.get_event_handlers()

    def pre_delete_detail_handlers(self):
        return self.get_event_handlers()

    def list_action(self, object_list, bundle):
        for event_handler in self.read_list_handlers():
            event_handler.list_action(object_list, bundle)

    def detail_action(self, object_list, bundle):
        for event_handler in self.read_list_handlers():
            event_handler.detail_action(object_list, bundle)


    def list_read(self, object_list, bundle):
        for event_handler in self.read_list_handlers():
            event_handler.list_read(object_list, bundle)

    def detail_read(self, object_list, bundle):
        for event_handler in self.read_detail_handlers():
            event_handler.detail_read(object_list, bundle)


    #Post method handlers
    def detail_created(self, object_list, bundle):
        for ev in self.create_detail_handlers():
            ev.detail_created(object_list, bundle)

    #put method handlers
    def detail_updated(self, object_list, bundle):
        for ev in self.update_detail_handlers():
            ev.detail_updated(object_list, bundle)

    def list_updated(self, object_list, bundle):
        for ev in self.update_list_handlers():
            ev.list_updated(object_list, bundle)

    #delete method handlers
    def list_deleted(self, object_list, bundle):
        for ev in self.delete_list_handlers():
            ev.list_deleted(object_list, bundle)

    def detail_deleted(self, object_list, bundle):
        for ev in self.delete_detail_handlers():
            ev.detail_deleted(object_list, bundle)

    def pre_detail_deleted(self, object_list, bundle):
        for ev in self.pre_delete_detail_handlers():
            ev.pre_detail_deleted(object_list, bundle)
